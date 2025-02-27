import logging
import mimetypes

from flask import Blueprint, jsonify, request, Response, url_for
from werkzeug.exceptions import BadRequest

from sciencebeam_utils.utils.collection import strip_all

from sciencebeam.utils.mime_type_constants import MimeTypes

from sciencebeam.pipeline_runners.simple_pipeline_runner import (
    create_simple_pipeline_runner_from_config,
    add_arguments as _add_arguments
)

LOGGER = logging.getLogger(__name__)

DEFAULT_FILENAME = 'file'


def add_arguments(parser, config, argv=None):
    _add_arguments(parser, config, argv=argv)


def parse_includes(includes):
    return includes and set(strip_all(includes.split(',')))


def create_api_blueprint(config, args):
    blueprint = Blueprint('api', __name__)

    pipeline_runner = create_simple_pipeline_runner_from_config(
        config, args
    )
    supported_types = pipeline_runner.get_supported_types()

    @blueprint.route("/")
    def _api_root():
        return jsonify({
            'links': {
                'convert': url_for('api._convert')
            }
        })

    @blueprint.route("/convert", methods=['POST'])
    def _convert():
        data_type = None
        includes = parse_includes(request.args.get('includes'))
        if not request.files:
            data_type = request.mimetype
            filename = request.args.get('filename')
            content = request.data
        elif 'file' not in request.files:
            raise BadRequest(
                'missing file named "file", found: %s ' % request.files.keys()
            )
        else:
            uploaded_file = request.files['file']
            data_type = uploaded_file.mimetype
            filename = uploaded_file.filename
            content = uploaded_file.read()

        if not content:
            raise BadRequest('no contents')

        if not filename:
            filename = '%s%s' % (
                DEFAULT_FILENAME, mimetypes.guess_extension(data_type) or ''
            )
            LOGGER.debug(
                'guessed filename %s for type %s',
                filename, data_type
            )
        elif data_type == 'application/octet-stream':
            data_type = mimetypes.guess_type(filename)[0]

        if data_type not in supported_types:
            error_message = 'unsupported type: %s (supported: %s)' % (
                data_type, ', '.join(sorted(supported_types))
            )
            LOGGER.info('%s (filename: %s)', error_message, filename)
            raise BadRequest(error_message)

        LOGGER.debug(
            'processing file: %s (%d bytes, type "%s")',
            filename, len(content), data_type
        )
        context = {
            'request_args': request.args
        }
        conversion_result = pipeline_runner.convert(
            content=content, filename=filename, data_type=data_type,
            includes=includes,
            context=context
        )
        response_content = conversion_result['content']
        response_type = conversion_result['type']
        LOGGER.debug(
            'response_content: %s (%s)',
            len(response_content), response_type
        )
        if response_type in {MimeTypes.TEI_XML, MimeTypes.JATS_XML}:
            response_type = 'text/xml'
        filename = conversion_result.get('filename')
        LOGGER.debug('output filename: %s', filename)
        headers = None
        if filename and response_type not in {'text/xml', MimeTypes.PDF}:
            headers = {
                'Content-Disposition': 'attachment; filename=%s' % filename
            }
        return Response(response_content, headers=headers, mimetype=response_type)

    @blueprint.route("/convert", methods=['GET'])
    def _convert_form():
        return (
            '''
            <!doctype html>
            <title>Convert PDF</title>
            <h1>Convert PDF</h1>
            <form method=post enctype=multipart/form-data>
            <input type=file name=file>
            <input type=submit value=Upload>
            </form>
            '''
        )

    return blueprint
