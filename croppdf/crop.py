#!/usr/bin/python
from PyPDF2 import PdfFileWriter, PdfFileReader

def croppdf(inputstream, parts):
    inputpdf = PdfFileReader(inputstream)
    numPages = inputpdf.getNumPages()
    print("document has %s pages." % numPages)

    for part in parts:
        name = part[0]
        pagenr = part[1]
        page = inputpdf.getPage(pagenr)
        output = PdfFileWriter()
        print(page.mediaBox.getUpperRight_x(), page.mediaBox.getUpperRight_y())
        page.trimBox.lowerLeft = (part[2], part[3])
        page.trimBox.upperRight = (part[4], part[5])
        page.cropBox.lowerLeft = (part[2], part[3])
        page.cropBox.upperRight = (part[4], part[5])
        output.addPage(page)
        with open("out_%s.pdf" %  name, "wb") as out_f:
            output.write(out_f) 


def main():
    with open("in.pdf", "rb") as in_f:
        croppdf(in_f, [["alma", 0, 50, 50, 200, 200],["korte", 0, 400, 400, 500, 500]])

if __name__ == "__main__":
    main()
