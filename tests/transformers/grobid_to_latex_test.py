import json
from io import BytesIO
from lxml import etree
from backports.tempfile import TemporaryDirectory
import os
from shutil import copyfile


from sciencebeam.transformers.grobid_to_latex import extractFigures, parseCoords, croppdf, tosvg


def filePath(file):
    return "tests/transformers/testdata/%s" %  file

class TestTEIToLatexFindFigures:

    def test_find_onefigure(self):
        xmltext = b'<TEI><figure xml:id="fig_1" coords="2,114.62,220.63,380.77,7.53"></figure></TEI>'
        assert extractFigures(BytesIO(xmltext)) == [("fig_1", [2, 114.62, 220.63, 380.77, 7.53])]

    def test_find_twofigure(self):
        xmltext = b'<TEI><figure xml:id="fig_1" coords="2,114.62,220.63,380.77,7.53"></figure><figure xml:id="fig_2" coords="3,114.62,220.63,380.77,7.53"></figure></TEI>'
        assert extractFigures(BytesIO(xmltext)) == [("fig_1", [2, 114.62, 220.63, 380.77, 7.53]),
        ("fig_2", [3, 114.62, 220.63, 380.77, 7.53])]

    def test_find_onefigure_deep(self):
        xmltext = b'<TEI><shiv><div><figure xml:id="fig_1" coords="2,114.62,220.63,380.77,7.53"></figure></div></shiv></TEI>'
        assert extractFigures(BytesIO(xmltext)) == [("fig_1", [2, 114.62, 220.63, 380.77, 7.53])]

    def test_full_file(self):
        with open(filePath("teidoc.xml")) as f:
             assert extractFigures(f) == [("fig_0", [1, 344.69, 331.35, 186.78, 8.47]),("fig_1", [2, 114.62, 220.63, 380.77, 7.53])]

class TestTEIToLatexParseCoords:

    def test_parse_simple_coord(self):
        assert parseCoords("1,20,20,30,30") == [1, 20, 20, 30, 30]

    def test_parse_floating_coord(self):
        assert parseCoords("1,20.4,20.3,30.2,30") == [1, 20.4, 20.3, 30.2, 30]

    def test_parse_pagenumber_int(self):
        result = parseCoords("1,20.4,20.3,30.2,30")
        assert result == [1, 20.4, 20.3, 30.2, 30]
        assert isinstance(result[0],int)

class TestTEIToLatexParseCrop:

    def test_crop_simple(self):
        with TemporaryDirectory('convert-to-latex') as workingDir:
            with open(filePath("in.pdf"), "rb") as f:
                parts = [("fig_1", [2, 114.62, 220.63, 380.77, 7.53])]
                expected = {'fig_1': '%s/fig_1.pdf' % workingDir}
                assert croppdf(f.read(), parts, workingDir) == expected
                assert os.path.isfile(expected['fig_1'])

    def test_crop_two_copyback(self):
        with TemporaryDirectory('convert-to-latex') as workingDir:
            with open(filePath("in.pdf"), "rb") as f:
                parts = [("fig_0", [1, 344.69, 331.35, 186.78, 8.47]), ("fig_1", [2, 114.62, 220.63, 380.77, 7.53])]
                expected = {
                    'fig_0': '%s/fig_0.pdf' % workingDir,
                    'fig_1': '%s/fig_1.pdf' % workingDir
                    }
                assert croppdf(f.read(), parts, workingDir) == expected
                assert os.path.isfile(expected['fig_0'])
                assert os.path.isfile(expected['fig_1'])
                copyfile(os.path.join(workingDir, "fig_0.pdf"), filePath("fig_0_res.pdf"))
                copyfile(os.path.join(workingDir, "fig_1.pdf"), filePath("fig_1_res.pdf"))
                assert False



class TestTEIToLatexParseToSvg:

    def test_parse_simple_coord(self):
        with TemporaryDirectory('convert-to-latex') as workingDir:
            copyfile(filePath("fig_0.pdf"), os.path.join(workingDir, "fig_0.pdf"))
            copyfile(filePath("fig_1.pdf"), os.path.join(workingDir, "fig_1.pdf"))
            croppedFiles = {
                'fig_0': '%s/fig_0.pdf' % workingDir,
                'fig_1': '%s/fig_1.pdf' % workingDir
            }
            expected = {
                'fig_0': '%s/fig_0.svg' % workingDir,
                'fig_1': '%s/fig_1.svg' % workingDir
            }
            assert tosvg(croppedFiles) == expected
            assert os.path.isfile(expected['fig_0'])
            assert os.path.isfile(expected['fig_1'])
            copyfile(os.path.join(workingDir, "fig_0.svg"), filePath("fig_0.svg"))
            copyfile(os.path.join(workingDir, "fig_1.svg"), filePath("fig_1.svg"))

