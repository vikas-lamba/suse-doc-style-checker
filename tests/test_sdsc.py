import pytest

import os
import sdsc
import sys
from lxml import etree


def test_sdsc_version(capsys):
    """checks for output of sdsc --version"""
    with pytest.raises(SystemExit):
        sdsc.main(["--version"])
    out, err = capsys.readouterr()
    assert sdsc.__version__ == out.split()[-1]


def test_tokenizer():
    """checks whether the tokenizer works as expected"""
    tokens = sdsc.tokenizer("This is a simple sentence.")
    assert(tokens == ["This", "is", "a", "simple", "sentence."])
    tokens = sdsc.tokenizer("This is a less simple sentence with a\xa0nbsp.")
    assert(tokens == ["This", "is", "a", "less",
                      "simple", "sentence", "with", "a", "nbsp."])


def test_sentencesegmenter():
    """checks whether sentencesegmenter behaves sane"""
    sentences = sdsc.sentencesegmenter(
        "This is a simple ##@command-2## sentence. This one as well.")
    assert(sentences == [
           "This is a simple ##@command-2## sentence", "This one as well"])
    sentences = sdsc.sentencesegmenter(
        "This is not a test in one go. openSUSE is not written with a capital letter.")
    assert(sentences == ["This is not a test in one go",
                         "openSUSE is not written with a capital letter"])
    sentences = sdsc.sentencesegmenter("This is a sentence, e.g. for me.")
    assert(sentences == ["This is a sentence, e.g. for me"])
    sentences = sdsc.sentencesegmenter("E. g. this is a sentence.")
    assert(sentences == ["E. g. this is a sentence"])
    sentences = sdsc.sentencesegmenter(
        "An above average chance stands e.g. Michael. Marta is also on the list.")
    assert(sentences == ["An above average chance stands e.g. Michael",
                         "Marta is also on the list"])


def test_isDupe():
    tokens = ["this", "is", "a", "test"]
    assert(sdsc.isDupe(tokens, 2) == 0)
    tokens = ["this", "is", "is", "a", "test"]
    assert(sdsc.isDupe(tokens, 2) == 1)
    tokens = ["this", "is", "this", "is", "a", "test"]
    assert(sdsc.isDupe(tokens, 2) == 2)
    tokens = ["this", "is", "(this", "is)", "a", "test"]
    assert(sdsc.isDupe(tokens, 2) == 0)


def test_highlighter():
    """checks whether the highlight function works"""
    xml = sdsc.highlight(["highlight", "these", "two", "words"], 1, 2)
    assert(xml == "highlight <highlight>these two</highlight> words")

# The xmltestcase fixture returns all files in tests/cases


def test_xml(xmltestcase):
    nr_errors = 0
    try:
        resultxml = sdsc.checkOneFile(xmltestcase)
    except:
        pytest.fail("Either testcase {0!r} or check XML have errors!".format(
            os.path.basename(xmltestcase)))

    # Parse the input file and gather all ids
    inputtree = etree.parse(xmltestcase)
    inputids = []
    for elem in inputtree.getiterator():
        id = elem.get("id")
        if id != None:
            if id.startswith("sdsc."):
                if id in inputids:
                    pytest.fail(
                        "Duplicate ID {0!r} in case {1!r}!".format(id, xmltestcase))

                inputids.append(id)
    if len(inputids) == 0:
        pytest.skip("No tests found in {0}".format(
            os.path.basename(xmltestcase)))

    # Parse the result file and collect ids of errors and warnings
    resulttree = etree.fromstring(resultxml)
    complaints = {}
    currentPartSource = ""
    for elem in resulttree.getiterator():
        if elem.tag == "part":
            currentPartSource = elem.get("source")
            complaints[currentPartSource] = []
        elif elem.tag == "result":
            elemType = elem.get("type", "info")
            if elemType == "info":
                # Not interested in those. They don't have an ID either...
                continue

            withinid = elem.findtext("location/withinid")
            message = elem.find("message")
            if withinid == None:
                withinid = elem.findtext("message/id")
                if withinid == None:
                    pytest.fail("No withinid found")

            formattedMessage = "<no message>"
            if message != None:
                formattedMessage = etree.tostring(
                    message, method="text", encoding='UTF-8').decode(encoding='UTF-8')  # bytes to str
                # Remove excessive whitespace and newlines
                formattedMessage = " ".join(formattedMessage.split()).strip()

            complaints[currentPartSource].append(
                {'id': withinid, 'message': formattedMessage, 'type': elemType})

    # Isolate unexpected warnings
    for checkmodule, complaintList in complaints.items():
        for complaint in complaintList:
            if complaint["id"].startswith("sdsc.expect") and checkmodule == "ids":
                continue  # Ignore warnings about "sdsc.expect" being an invalid ID

            if not complaint["id"].startswith("sdsc.expect.{0}.{1}".format(complaint["type"], checkmodule)):
                print("Unexpected {0} {1!r} generated by module {2!r} for ID {3!r}.".format(complaint[
                      "type"], complaint["message"], checkmodule, complaint["id"]), file=sys.stderr)
                nr_errors += 1

    # Now check for missing errors and warnings
    for id in inputids:
        if not id.startswith("sdsc.expect."):
            continue

        # id = "sdsc.expect.error.a-an" => idArr = [ "sdsc", "expect", "error",
        # "a-an" ]
        idArr = id.split(".")
        found = False
        if idArr[3] in complaints:
            found = sum(complaint["id"] == id and complaint["type"] == idArr[
                        2] for complaint in complaints[idArr[3]])

        if not found:
            print("Expected {0} for ID {1!r} generated by module {2!r}.".format(
                idArr[2], id, idArr[3]), file=sys.stderr)
            nr_errors += 1

    if nr_errors > 0:
        pytest.fail(msg="Test {0!r} failed with {1} errors!".format(
            os.path.basename(xmltestcase), nr_errors), pytrace=False)
