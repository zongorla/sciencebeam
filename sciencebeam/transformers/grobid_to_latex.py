import logging
import os
import io
from lxml import etree
from lxml.etree import Element, ElementTree
from PyPDF2 import PdfFileWriter, PdfFileReader
from backports.tempfile import TemporaryDirectory

LOGGER = logging.getLogger(__name__)

def getAttr(xelement, attr):
    attr = xelement.xpath("./@%s" % attr)
    if len(attr) == 1:
        return attr[0]
    else:
        return None

def extractFigures(xml):

    if isinstance(xml,(str,bytes)):
        tree = etree.fromstring(xml)
    else:
        tree = etree.parse(xml)
    results = []
    for figurenode in tree.xpath("//*[local-name()='figure']"):
        LOGGER.debug("%s", figurenode.tag)
        coords = getAttr(figurenode, "coords")
        figureid = getAttr(figurenode, "xml:id")
        if coords is None:
            LOGGER.debug("No coord found for figure")
        if figureid is None:
            LOGGER.debug("No id found for figure")
        if not (figureid is None or coords is None):
            results.append((figureid, parseCoords(coords)))
    return results

def parseCoords(coordsString):
    LOGGER.debug(coordsString)
    res = list(map(lambda x: float(x),coordsString.split(";")[0].split(',')))
    res[0] = int(res[0])
    return res

def transform(point,reference):
    res = (point[0],reference[1] - point[1])
    print(res)
    return res

def croppdf(inputstream, parts, workingdir):
    if isinstance(inputstream, bytes):
        inputpdf = PdfFileReader(io.BytesIO(inputstream))
    elif isinstance(inputstream, str):
        inputpdf = PdfFileReader(io.StringIO(inputstream))
    else:
        inputpdf = PdfFileReader(inputstream)

    inputpdf = PdfFileReader(io.BytesIO(inputstream))
    numPages = inputpdf.getNumPages()
    print("document has %s pages." % numPages)
    pdffiles = {}
    for part in parts:
        name = part[0]
        coords = part[1]
        page = inputpdf.getPage(coords[0]-1)
        output = PdfFileWriter()
        upperRightMax = (page.mediaBox.getUpperRight_x(), page.mediaBox.getUpperRight_y())
        print(upperRightMax)
        lowerLeft = transform((coords[1], coords[2]), upperRightMax)
        upperRight = transform((coords[1] + coords[3], coords[2] + coords[4]), upperRightMax)
        page.trimBox.lowerRight = lowerLeft
        page.trimBox.upperLeft = upperRight
        page.cropBox.lowerRight = lowerLeft
        page.cropBox.upperLeft = upperRight
        output.addPage(page)
        pdffiles[name] = os.path.join(workingdir, "%s.pdf" %  name)
        with open(pdffiles[name], "wb") as out_f:
            output.write(out_f)
        
    return pdffiles

def tosvg(pdfFiles):
    svgFiles = {}
    for pdfFile in pdfFiles:
        sourceFile = pdfFiles[pdfFile]
        targetFile = pdfFiles[pdfFile][:-3] + "svg"
        command = "pdf2svg %s %s" % (sourceFile, targetFile)
        LOGGER.info(os.popen(command).read())
        svgFiles[pdfFile] = targetFile
    return svgFiles

def toZip(workingDir):
    commandTempl = "cd %s && zip %s/article.zip %s/*" % (workingDir, workingDir, workingDir)
    commandTempl += "%s"
    LOGGER.info(os.popen(commandTempl % (".tex")).read())
    LOGGER.info(os.popen(commandTempl % (".svg")).read())
    LOGGER.info(os.popen(commandTempl % (".xml")).read())

#s.path.expandvars
def convertlatex(x, workingdir):
    sourceFilePath = "%s/teidoc.xml" % (workingdir)
    resultFilePath = "%s/teidoc.tex" % (workingdir)
    f = open(sourceFilePath, "wb")
    f.write(x)
    f.flush()
    f.close()
    commandpath = "xslt/Stylesheets/bin/teitolatex"
    command = commandpath + " --odd " + sourceFilePath + " " + resultFilePath 
    LOGGER.info(os.popen(command).read())
    return resultFilePath



class teixslt_transformer_from_file_tolatex:
    def __init__(self,to_string=True, pretty_print=False):
        self.to_string = to_string
        self.pretty_print = pretty_print


    def __call__(self, teixml, pdf):
        with TemporaryDirectory('convert-to-latex') as workingDir:
            figures = extractFigures(teixml)
            latexFile = convertlatex(teixml, workingDir)
            LOGGER.debug(figures)
            pdfFiles = croppdf(pdf, figures, workingDir)
            LOGGER.debug(pdfFiles)
            svgFiles = tosvg(pdfFiles)
            LOGGER.debug(svgFiles)
            toZip(workingDir)   
            with open("%s/article.zip" % workingDir, "rb") as f:
                return f.read()
