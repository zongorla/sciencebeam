import argparse  # pylint: disable=unused-import

from sciencebeam.transformers.grobid_service import (
    grobid_service,
    GrobidApiPaths
)

from sciencebeam.transformers.grobid_to_latex import teixslt_transformer_from_file_tolatex

from sciencebeam.utils.mime_type_constants import MimeTypes

from . import Pipeline, FunctionPipelineStep, FieldNames, StepDataProps

DEFAULT_GROBID_ACTION = GrobidApiPaths.PROCESS_HEADER_DOCUMENT
DEFAULT_GROBID_XSLT_PATH = 'xslt/grobid-jats.xsl'

LOCAL_GROBID_API_URL = 'http://localhost:8080/api'
LOCAL_TEILATEX_API_URL = 'http://localhost:8080/api'

HEADER_FIELDS = {
    FieldNames.TITLE,
    FieldNames.ABSTRACT,
    FieldNames.AUTHORS,
    FieldNames.AFFILIATIONS
}


def has_only_header_fields(fields):
    return fields and not set(fields) - HEADER_FIELDS


def get_default_grobid_action_for_fields(fields):
    return (
        GrobidApiPaths.PROCESS_HEADER_DOCUMENT
        if has_only_header_fields(fields)
        else GrobidApiPaths.PROCESS_FULL_TEXT_DOCUMENT
    )


class GrobidLatexPipeline(Pipeline):
    def add_arguments(self, parser, config, argv=None):
        # type: (argparse.ArgumentParser, dict, object) -> None
        grobid_group = parser.add_argument_group('GrobidLatex')
        grobid_group.add_argument(
            '--grobid-url', required=False, default=None,
            help='Base URL to the Grobid service'
        )
        grobid_group.add_argument(
            '--grobid-action', required=False,
            default=None,
            help='Name of the Grobid action'
            ' (by default determined depending on the requested fields)'
        )
        grobid_group.add_argument(
            '--no-grobid-xslt', action='store_true',
            help='Disable translation using XSLT'
        )
        grobid_group.add_argument(
            '--grobid-xslt-path', default=DEFAULT_GROBID_XSLT_PATH,
            help='Path to XSLT file translating results to JATS'
        )
        grobid_group.add_argument(
            '--no-grobid-pretty-print', action='store_true',
            help='Disable pretty print of XSLT output'
        )

    def get_steps(self, config, args):
        # type: (dict, object) -> list
        grobid_url = args.grobid_url
        if not grobid_url:
            grobid_url = LOCAL_GROBID_API_URL
            start_grobid_service = True
        else:
            start_grobid_service = False

        call_grobid = grobid_service(
            grobid_url, args.grobid_action, start_service=start_grobid_service
        )

        def convert_to_tei(pdf_filename, pdf_content, includes, context):
            context["pdfdata"] = pdf_content
            return call_grobid(  # pylint: disable=redundant-keyword-arg
                (pdf_filename, pdf_content),
                path=args.grobid_action or get_default_grobid_action_for_fields(
                    includes
                )
            )[1]

        steps = [
            FunctionPipelineStep(lambda data, context={}, **_: {
                StepDataProps.CONTENT: convert_to_tei(
                    pdf_filename=data[StepDataProps.FILENAME],
                    pdf_content=data[StepDataProps.CONTENT],
                    includes=data.get(StepDataProps.INCLUDES),
                    context=context),
                StepDataProps.TYPE: MimeTypes.TEI_XML
            }, {MimeTypes.PDF}, 'Convert to TEI')
        ]
        if not args.no_grobid_xslt:
            latex_transformer = teixslt_transformer_from_file_tolatex()
            steps.append(FunctionPipelineStep(lambda d, context={}, **_: {
                StepDataProps.CONTENT: latex_transformer(d[StepDataProps.CONTENT],context["pdfdata"]),
                StepDataProps.TYPE: MimeTypes.ZIP
            }, {MimeTypes.TEI_XML}, 'TEI to LATEX'))
        return steps


PIPELINE = GrobidLatexPipeline()
