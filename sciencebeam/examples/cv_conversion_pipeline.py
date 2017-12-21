from __future__ import absolute_import

import argparse
import os
import logging
from itertools import islice
from io import BytesIO

import apache_beam as beam
from apache_beam.io.filesystems import FileSystems
from apache_beam.options.pipeline_options import PipelineOptions, SetupOptions

import tensorflow as tf
import numpy as np
from lxml import etree

from PIL import Image

from sciencebeam_gym.utils.collection import (
  extend_dict,
  remove_keys_from_dict
)

from sciencebeam_gym.beam_utils.utils import (
  TransformAndCount,
  TransformAndLog,
  MapOrLog,
  PreventFusion
)

from sciencebeam_gym.beam_utils.csv import (
  ReadDictCsv
)

from sciencebeam_gym.beam_utils.io import (
  read_all_from_path,
  save_file_content
)

from sciencebeam_gym.beam_utils.main import (
  add_cloud_args,
  process_cloud_args
)

from sciencebeam_gym.structured_document.lxml import (
  LxmlStructuredDocument
)

from sciencebeam_gym.preprocess.color_map import (
  parse_color_map_from_file
)

from sciencebeam_gym.beam_utils.io import (
  find_matching_filenames
)

from sciencebeam_gym.preprocess.preprocessing_utils import (
  change_ext,
  relative_path,
  join_if_relative_path,
  convert_pdf_bytes_to_lxml,
  pdf_bytes_to_png_pages,
  save_pages,
  parse_page_range
)

from sciencebeam_gym.inference_model import (
  load_inference_model
)

from sciencebeam_gym.inference_model.annotate_using_predictions import (
  annotate_structured_document_using_predicted_images,
  AnnotatedImage
)

from sciencebeam_gym.inference_model.extract_to_xml import (
  extract_structured_document_to_xml
)

def get_logger():
  return logging.getLogger(__name__)

class MetricCounters(object):
  FILES = 'files'
  CONVERT_PDF_TO_LXML_ERROR = 'ConvertPdfToLxml_error_count'
  CONVERT_PDF_TO_PNG_ERROR = 'ConvertPdfToPng_error_count'
  CONVERT_LXML_TO_SVG_ANNOT_ERROR = 'ConvertPdfToSvgAnnot_error_count'
  CV_PREDICTION_ERROR = 'ComputerVisionPrediction_error_count'
  ANNOTATE_USING_PREDICTION_ERROR = 'AnnotateLxmlUsingPrediction_error_count'
  EXTRACT_TO_XML_ERROR = 'ExtractToXml_error_count'

def lazy_cached_value(value_fn):
  cache = {}
  def wrapper():
    value = cache.get('value')
    if value is None:
      value = value_fn()
      cache['value'] = value
    return value
  return wrapper

def annotate_lxml_using_predicted_images(lxml_content, prediction_images, color_map):
  structured_document = LxmlStructuredDocument(
    etree.parse(BytesIO(lxml_content))
  )
  structured_document = annotate_structured_document_using_predicted_images(
    structured_document, (
      AnnotatedImage(prediction_image, color_map)
      for prediction_image in prediction_images
    )
  )
  return etree.tostring(structured_document.root)

def extract_annotated_lxml_to_xml(annotated_lxml_content):
  structured_document = LxmlStructuredDocument(
    etree.parse(BytesIO(annotated_lxml_content))
  )

  xml_root = extract_structured_document_to_xml(structured_document)
  return etree.tostring(xml_root, pretty_print=True)

def image_data_to_png(image_data):
  image = Image.fromarray(image_data, 'RGB')
  out = BytesIO()
  image.save(out, 'png')
  return out.getvalue()

def create_inference_model_wrapper(export_dir):
  session_cache = lazy_cached_value(lambda: tf.InteractiveSession())
  inference_model_cache = lazy_cached_value(
    lambda: load_inference_model(export_dir, session=session_cache())
  )
  def wrapper(png_pages):
    input_data = [
      np.asarray(Image.open(BytesIO(png_page)).convert('RGB'), dtype=np.uint8)
      for png_page in png_pages
    ]
    output_img_data_batch = inference_model_cache()(input_data, session=session_cache())
    return output_img_data_batch
  return wrapper

def configure_pipeline(p, opt):
  image_size = (
    (opt.image_width, opt.image_height)
    if opt.image_width and opt.image_height
    else None
  )
  page_range = opt.pages

  inference_model_wrapper = create_inference_model_wrapper(opt.model_export_dir)

  color_map = parse_color_map_from_file(opt.color_map)

  if opt.pdf_file_list:
    pdf_urls = (
      p |
      "ReadFileUrls" >> ReadDictCsv(opt.pdf_file_list, limit=opt.limit) |
      "TranslateFileUrls" >> beam.Map(lambda row: row['pdf_url'])
    )
  else:
    pdf_urls = (
      p |
      beam.Create([
        join_if_relative_path(opt.base_data_path, opt.pdf_path)
      ]) |
      "FindFiles" >> TransformAndLog(
        beam.FlatMap(
          lambda pattern: islice(
            find_matching_filenames(pattern),
            opt.limit
          )
        ),
        log_prefix='files: ',
        log_level='debug'
      )
    )

  cv_predictions = (
    pdf_urls |
    PreventFusion() |

    "ReadFileContent" >> TransformAndCount(
      beam.Map(lambda pdf_url: {
        'pdf_filename': pdf_url,
        'pdf_content': read_all_from_path(pdf_url),
      }),
      MetricCounters.FILES
    ) |

    "ConvertPdfToLxml" >> MapOrLog(lambda v: extend_dict(v, {
      'lxml_content': convert_pdf_bytes_to_lxml(
        v['pdf_content'], path=v['pdf_filename'],
        page_range=page_range
      )
    }), log_fn=lambda e, v: (
      get_logger().warning(
        'caught exception (ignoring item): %s, pdf: %s',
        e, v['pdf_filename'], exc_info=e
      )
    ), error_count=MetricCounters.CONVERT_PDF_TO_LXML_ERROR) |

    "ConvertPdfToPng" >> MapOrLog(lambda v: remove_keys_from_dict(
      extend_dict(v, {
        'pdf_png_pages':  list(pdf_bytes_to_png_pages(
          v['pdf_content'],
          dpi=90, # not used if the image is scaled
          image_size=image_size,
          page_range=page_range
        ))
      }),
      keys_to_remove={'pdf_content'}
    ), error_count=MetricCounters.CONVERT_PDF_TO_PNG_ERROR) |

    "ComputerVisionPrediction" >> MapOrLog(lambda v: remove_keys_from_dict(
      extend_dict(v, {
        'prediction_png_pages': inference_model_wrapper(v['pdf_png_pages'])
      }),
      keys_to_remove={'pdf_png_pages'}
    ), error_count=MetricCounters.CV_PREDICTION_ERROR)
  )

  if opt.save_cv_output:
    _ = (
      cv_predictions |
      "SaveComputerVisionOutput" >> TransformAndLog(
        beam.Map(lambda v: save_pages(
          FileSystems.join(
            opt.output_path,
            change_ext(
              relative_path(opt.base_data_path, v['pdf_filename']),
              None, '.cv-png.zip'
            )
          ),
          '.png',
          [image_data_to_png(image_data) for image_data in v['prediction_png_pages']]
        )),
        log_fn=lambda x: get_logger().info('saved cv output: %s', x)
      )
    )

  annotated_lxml = (
    cv_predictions |
    "AnnotateLxmlUsingPrediction" >> MapOrLog(lambda v: remove_keys_from_dict(
      extend_dict(v, {
        'annotated_lxml_content': annotate_lxml_using_predicted_images(
          v['lxml_content'], v['prediction_png_pages'], color_map
        )
      }),
      keys_to_remove={'pdf_png_pages', 'lxml_content'}
    ), error_count=MetricCounters.ANNOTATE_USING_PREDICTION_ERROR)
  )

  if opt.save_annot_lxml:
    _ = (
      annotated_lxml |
      "SaveAnnotLxml" >> TransformAndLog(
        beam.Map(lambda v: save_file_content(
          FileSystems.join(
            opt.output_path,
            change_ext(
              relative_path(opt.base_data_path, v['pdf_filename']),
              None, '.annot.lxml.gz'
            )
          ),
          v['annotated_lxml_content']
        )),
        log_fn=lambda x: get_logger().info('saved annoted lxml to: %s', x)
      )
    )

  extracted_xml = (
    annotated_lxml |
    "ExtractToXml" >> MapOrLog(lambda v: remove_keys_from_dict(
      extend_dict(v, {
        'extracted_xml': extract_annotated_lxml_to_xml(
          v['annotated_lxml_content']
        )
      }),
      keys_to_remove={'annotated_lxml_content'}
    ), error_count=MetricCounters.EXTRACT_TO_XML_ERROR)
  )

  _ = (
    extracted_xml |
    "WriteXml" >> TransformAndLog(
      beam.Map(lambda v: save_file_content(
        FileSystems.join(
          opt.output_path,
          change_ext(
            relative_path(opt.base_data_path, v['pdf_filename']),
            None, opt.output_suffix
          )
        ),
        v['extracted_xml']
      )),
      log_fn=lambda x: get_logger().info('saved xml to: %s', x)
    )
  )


def add_main_args(parser):
  parser.add_argument(
    '--data-path', type=str, required=True,
    help='base data path'
  )

  source_group = parser.add_mutually_exclusive_group(required=True)
  source_group.add_argument(
    '--pdf-path', type=str, required=False,
    help='path to pdf file(s), relative to data-path'
  )
  source_group.add_argument(
    '--pdf-file-list', type=str, required=False,
    help='path to pdf csv/tsv file list (with a "pdf_url" column; it may contain other columns)'
  )

  parser.add_argument(
    '--limit', type=int, required=False,
    help='limit the number of file pairs to process'
  )

  parser.add_argument(
    '--output-path', required=False,
    help='Output directory to write results to.'
  )

  parser.add_argument(
    '--output-suffix', required=False, default='.cv.xml',
    help='Output file suffix to add to the filename (excluding the file extension).'
  )

  parser.add_argument(
    '--save-cv-output', action='store_true', default=False,
    help='enable saving of computer vision output (png pages)'
  )

  parser.add_argument(
    '--save-annot-lxml', action='store_true', default=False,
    help='enable saving of annotated lxml'
  )

  parser.add_argument(
    '--debug', action='store_true', default=False,
    help='enable debug output'
  )

  parser.add_argument(
    '--image-width', type=int, required=False,
    default=256,
    help='image width of resulting PNGs'
  )
  parser.add_argument(
    '--image-height', type=int, required=False,
    default=256,
    help='image height of resulting PNGs'
  )

  parser.add_argument(
    '--pages', type=parse_page_range, default=None,
    help='only processes the selected pages'
  )

  parser.add_argument(
    '--model-export-dir', type=str, required=True,
    help='path to model export dir'
  )

  parser.add_argument(
    '--color-map', default='color_map.conf',
    help='color map to use'
  )

def process_main_args(args):
  args.base_data_path = args.data_path.replace('/*/', '/')

  if not args.output_path:
    args.output_path = os.path.join(
      os.path.dirname(args.base_data_path),
      os.path.basename(args.base_data_path + '-results')
    )

def parse_args(argv=None):
  parser = argparse.ArgumentParser()
  add_main_args(parser)
  add_cloud_args(parser)

  args = parser.parse_args(argv)

  if args.debug:
    logging.getLogger().setLevel('DEBUG')

  process_main_args(args)
  process_cloud_args(
    args, args.output_path,
    name='sciencbeam-convert'
  )

  get_logger().info('args: %s', args)

  return args

def run(argv=None):
  args = parse_args(argv)

  # We use the save_main_session option because one or more DoFn's in this
  # workflow rely on global context (e.g., a module imported at module level).
  pipeline_options = PipelineOptions.from_dictionary(vars(args))
  pipeline_options.view_as(SetupOptions).save_main_session = True

  with beam.Pipeline(args.runner, options=pipeline_options) as p:
    configure_pipeline(p, args)

    # Execute the pipeline and wait until it is completed.


if __name__ == '__main__':
  logging.basicConfig(level='INFO')

  run()
