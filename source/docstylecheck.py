#!/usr/bin/python3
# -*- coding: UTF-8 -*-

import argparse
import glob
import os.path
import re
import subprocess
import sys
import time
import argparse
import random
import webbrowser
try:
    from lxml import etree
except ImportError:
    sys.exit("Could not import from LXML. Is LXML for Python 3 installed?")

__programname__ = "Documentation Style Checker"
__version__ = "0.1.0pre"
__author__ = "Stefan Knorr"
__license__ = "MIT"
__description__ = "checks a given DocBook XML file for stylistic errors"

# global variables
args = None
# terminology data structures
termdataid = None
ignoredpattern = None
accepts = []
patterns = []           # per acceptpattern, add list of list of patterns
contextpatterns = []    # per pattern list, add list of contextpatterns
onepattern = ""         # one long pattern is cheaper than many short ones

# In manglepattern(), only catch patterns that are not literal and are not
# followed by an indicator of a lookahead/lookbehind (?) or are already
# non-capturing groups
parentheses = re.compile( r'(?<!\\)\((?![\?|\:])' )


# TODO: Get rid of the entire "positional arguments" thing that argparse adds
# (self-explanatory anyway). Get rid of "optional arguments" header. Make sure
# least important options (--help, --version) are listed last. Also, I really
# liked being able to use sentences in the parameter descriptions.
def parseargs():
    parser = argparse.ArgumentParser(
        usage = "%(prog)s [options] inputfile [outputfile]",
        description = __description__ )
    parser.add_argument('-v', '--version',
        action = 'version',
        version = __programname__ + " " + __version__,
        help = "show version number and exit")
    parser.add_argument( '-b', '--bookmarklet',
        action = 'store_true',
        default = False,
        help = """open page that lets you install a bookmarklet to manage style
            checker results""" )
    parser.add_argument( '-s', '--show',
        action = 'store_true',
        default = False,
        help = """show final report in $BROWSER, or default browser if unset; not
            all browsers open report files correctly and for some users, a text
            editor will open; in such cases, set the BROWSER variable with:
            export BROWSER=/MY/FAVORITE/BROWSER ; Chromium or Firefox will both
            do the right thing""" )
    parser.add_argument( '-e', '--errors',
        action = 'store_true',
        default = False,
        help = """output error messages, but do not output warning or
            information messages""" )
    parser.add_argument( '--performance',
        action = 'store_true',
        default = False,
        help = "write some performance measurements to stdout" )
    parser.add_argument( 'inputfile', type=argparse.FileType('r') )
    parser.add_argument( 'outputfile', nargs = "?" )

    return parser.parse_args()

def printcolor( message, type = None ):
    if sys.stdout.isatty():
        if type == 'error':
            print( '\033[0;31m' + message + '\033[0m' )
        else:
            print( '\033[0;32m' + message + '\033[0m' )
    else:
        print( message )

def linenumber( context ):
    return context.context_node.sourceline

def termcheck( context, termfileid, content, contentpretty, contextid, basefile ):
    # FIXME: Modes: para, title?
    messages = []

    global termdataid
    global ignoredpattern
    global accepts
    global patterns
    global contextpatterns
    global onepattern

    if content:
        # I get this as a list with one lxml.etree._ElementUnicodeResult, not
        # as a list with a string.
        # For whatever reason, this made termcheckmessage() crash
        # happily and semi-randomly.
        content = str( content[0] )

    if not content:
        return messages

    if basefile:
        basefile = basefile[0]
    else:
        basefile = None

    if contextid:
        contextid = contextid[0]
    else:
        contextid = None

    # onepattern is a concatenated list of all patterns of the terminology
    # file which are within a pattern1 element
    # how useful is onepattern?
    #   + the overhead for onepattern is (currently) akin to adding 1 word
    #     to every paragraph
    #   + 30-40 % of paragraphs are skipped because of onepattern
    #   + the paragraphs skipped because of onepattern average at
    #     5-10 words
    #   = worst case: similar time, best case: slight win,
    #     more compliant documentation will tip the scale in our favour
    if onepattern:
        if not onepattern.search( content ):
            if args.performance:
                print("skipped entire paragraph\n")
            return messages

    # This if/else block should not be necessary (if there is content,
    # there should always also be pretty content, but that depends on the
    # XSLT used for checking). It hopefully won't hurt either.
    if contentpretty:
        contentpretty = str( contentpretty[0] )
    else:
        contentpretty = content


    # This should get us far enough for now
    sentences = sentencetokenizer( content )

    for sentence in sentences:
        # FIXME: Get something better than s.split. Some
        # existing tokenisers are overzealous, such as the default one from
        # NLTK.
        words = sentence.split()
        totalwords = len( words )

        if args.performance:
            timestartmatch = time.time()

        skipcount = 0
        for wordposition, word in enumerate(words):
            # Idea here: if we previously matched a multi-word pattern, we can
            # simply skip the next few words since they were matched already.
            if skipcount > 0:
                skipcount -= 1
                continue

            word = replacepunctuation( word, "start" )

            # don't burn time on checking small words like "the," "a," "of" etc.
            # (configurable from within terminology file)
            if ignoredpattern:
                if ignoredpattern.match( word ):
                    continue


            # When a pattern already matches on a word, don't try to find more
            # problems with it.
            trynextterm = True

            # Use the *patterns variables defined above to match all patterns
            # over everything that is left.
            # Don't use enumerate with patterngroupposition, its value
            # depends on being defined in this scope.
            patterngroupposition = 0
            for acceptposition, accept in enumerate( accepts ):
                if trynextterm:
                    acceptword = accept[0]
                    acceptcontext = accept[1]

                    # FIXME: variable names are a bit of a mouthful
                    patterngroupstoaccept = patterns[ acceptposition ]
                    for patterngrouppatterns in patterngroupstoaccept:
                        if not trynextterm:
                            break
                        if ( wordposition + len( patterngrouppatterns ) ) > totalwords:
                            patterngroupposition += 1
                            continue
                        trycontextpatterns = True
                        matchwords = ""
                        # Don't use enumerate for patterngrouppatternposition,
                        # its value depends on breaks.
                        patterngrouppatternposition = 0
                        skipcounttemporary = 0
                        for patterngrouppattern in patterngrouppatterns:
                            patternposition = wordposition + patterngrouppatternposition
                            if patternposition > ( totalwords - 1 ):
                                trycontextpatterns = False
                                break
                            matchword = None

                            # This if/else is a bit dumb, but we already did
                            # replacepunctuation() on word, so it is not
                            # the same as words[ patternposition ] any more.
                            if patterngrouppatternposition == 0:
                                matchword = patterngrouppattern.match( word )
                            else:
                                matchword = patterngrouppattern.match( words[ patternposition ] )
                            if matchword:
                                if not patterngrouppatternposition == 0:
                                    # The first matched pattern should not make
                                    # us skip a word ahead.
                                    skipcounttemporary += 1
                                    matchwords += " "
                                matchwords += matchword.group(0)
                            else:
                                trycontextpatterns = False
                                break
                            patterngrouppatternposition += 1

                        contextmatches = 0
                        contextpatternstopatterngroup = contextpatterns[ patterngroupposition ]
                        if trycontextpatterns:
                            if contextpatternstopatterngroup[0][0] is None:
                                # easy positive
                                skipcount = skipcounttemporary
                                trynextterm = False
                                line = linenumber ( context )
                                messages.append( termcheckmessage(
                                    acceptword, acceptcontext, matchwords, line,
                                    contentpretty, contextid, basefile ) )
                            else:
                                for contextpattern in contextpatternstopatterngroup:
                                    if contextpattern[0]:
                                        contextmatches += matchcontextpattern( words,
                                                            wordposition, totalwords,
                                                            patterngrouppatternposition,
                                                            contextpattern )

                            if ( len( contextpatternstopatterngroup ) == contextmatches ):
                                skipcount = skipcounttemporary
                                trynextterm = False
                                line = linenumber ( context )
                                messages.append( termcheckmessage(
                                    acceptword, acceptcontext, matchwords, line,
                                    contentpretty, contextid, basefile ) )
                            elif ( len( contextpatternstopatterngroup ) < contextmatches ):
                                print("hui!", len( contextpatternstopatterngroup ), contextmatches )
                        patterngroupposition += 1

    if args.performance:
        timeendmatch = time.time()
        timediffmatch = timeendmatch - timestartmatch
        print( """words: %s
time for this para: %s
average time per word: %s\n"""
            % ( str( totalwords ), str( timediffmatch ),
                str( timediffmatch / (totalwords + .001 ) ) ) )

    return messages

def matchcontextpattern( words, wordposition, totalwords,
                         patterngrouppatternposition, contextpattern ):

    contextwheres = contextpattern[1]
    contextmatches = 0

    contextstring = ""
    for contextwhere in contextwheres:
        contextposition = None
        contextposition = wordposition + contextwhere
        if contextwhere > 0:
            # patterngrouppatternposition is at 1,
            # even if there was just one pattern
            contextposition += patterngrouppatternposition - 1
        if ( contextposition < 0 or contextposition > ( totalwords - 1 ) ):
            continue
        else:
            contextstring += str( words[ contextposition ] ) + " "

    # We could check for an empty context
    # here and then not run any check,
    # but that would lead to wrong
    # results when doing negative
    # matching.

    # positive matching
    if contextpattern[2]:
        if contextstring:
            contextword = contextpattern[0].search( contextstring )
            if contextword:
                contextmatches += 1
    # negative matching
    else:
        if not contextstring:
            contextmatches += 1
        else:
            contextword = contextpattern[0].search( contextstring )
            if not contextword:
                contextmatches += 1

    return contextmatches

def buildtermdata( context, terms, ignoredwords, useonepattern ):

    global termdataid
    global ignoredpattern
    global accepts
    global patterns
    global contextpatterns
    global onepattern

    termdataid = None
    ignoredpattern = None
    accepts = []
    patterns = []
    contextpatterns = []

    # Not much use, but ... let's make this a real boolean.
    useonepatterntemp = True
    if useonepattern:
        if useonepattern[0] == 'no':
            useonepatterntemp = False
    useonepattern = useonepatterntemp

    if useonepattern:
        onepattern = ""
    else:
        onepattern = None

    if args.performance:
        timestartbuild = time.time()

    termdataid = random.randint(0, 999999999)

    if ignoredwords:
        ignoredpattern = re.compile( manglepattern( ignoredwords[0], 0 ),
            flags = re.I )

    firstpatterngroup = True
    for term in terms:
        accepts.append( prepareaccept( term ) )

        patternsofterm = []
        patterngroupxpaths = term.xpath( 'patterngroup' )
        for patterngroupxpath in patterngroupxpaths:
            preparedpatterns = preparepatterns( patterngroupxpath, useonepattern )
            if useonepattern:
                onepatternseparator = '|'
                if firstpatterngroup:
                    onepatternseparator = ''
                    firstpatterngroup = False
                # use (?: to create non-capturing groups: the re module's
                # implementation only supports up to 100 named groups per
                # expression
                onepattern += '%s(?:%s)' % ( onepatternseparator, preparedpatterns[1] )

            patternsofterm.append( preparedpatterns[0] )

            contextpatternsofpatterngroup = []
            contextpatternxpaths = patterngroupxpath.xpath( 'contextpattern' )
            if contextpatternxpaths:
                for contextpatternxpath in contextpatternxpaths:
                    contextpatternsofpatterngroup.append(
                        preparecontextpatterns( contextpatternxpath ) )
            else:
                contextpatternsofpatterngroup.append( [ None ] )
            contextpatterns.append( contextpatternsofpatterngroup )

        patterns.append( patternsofterm )

    if useonepattern:
        onepattern = re.compile( onepattern, flags = re.I )

    if args.performance:
        timeendbuild = time.time()
        print( "time to build: %s" % str( timeendbuild - timestartbuild ) )
    return termdataid

def manglepattern( pattern, onepatternmode ):
    # FIXME: This is messy and not really doing what I want it to.
    global parentheses

    if onepatternmode:
        # use (?: to create non-capturing groups: the re module's
        # implementation only supports up to 100 named groups per
        # expression
        pattern = parentheses.sub('(?:', pattern)

    # \b is messy: inside a character class, it is interpreted as a
    # backspace character. Outside, it marks word boundaries. However, we
    # want to be able to check words that start/end with punctuation (such
    # as abbreviations), too.
    pattern = r'\b' + pattern + r'\b'

    return pattern

def prepareaccept( term ):
    acceptwordxpath = term.xpath( 'accept[1]/word[1]' )
    acceptwordxpathcontent = None
    if acceptwordxpath:
        acceptwordxpathcontent = acceptwordxpath[0].text
    # If there is no accepted word, we don't care about the context
    if acceptwordxpathcontent:
        acceptlist = [ acceptwordxpathcontent ]
        acceptcontextxpath = term.xpath( 'accept[1]/context[1]' )
        if acceptcontextxpath:
            acceptlist.append( acceptcontextxpath[0].text )
        else:
            acceptlist.append( None )

        return acceptlist
    else:
        return [ None, None ]

def preparepatterns( patterngroupxpath, useonepattern ):
    patternsofpatterngroup = []
    patternforonepattern = None

    for i in range(1,6):
        patternxpath = patterngroupxpath.xpath( 'pattern%s[1]' % i )
        patternxpathcontent = None
        if patternxpath:
            patternxpathcontent = patternxpath[0].text

        if not patternxpathcontent:
            if i == 1:
                emptypatternmessage( 'pattern1' )
            else:
                # FIXME: the implementation assumes that the e.g. the second
                # pattern can only come from the pattern2 element --
                # what about skipped pattern{x} elements?
                break
        else:
            patternxpathcontent = manglepattern( patternxpath[0].text, 0 )
            if i == 1 and useonepattern:
                patternforonepattern = manglepattern( patternxpath[0].text, 1 )

        pattern = None
        if getattribute( patternxpath[0], 'case' ) == 'keep':
            pattern = re.compile( patternxpathcontent )
        else:
            pattern = re.compile( patternxpathcontent, flags = re.I )
        patternsofpatterngroup.append( pattern )

    return [ patternsofpatterngroup, patternforonepattern ]

def preparecontextpatterns( contextpatternxpath ):
    contextpatternxpathcontent = contextpatternxpath.text
    if not contextpatternxpathcontent:
        emptypatternmessage( 'contextpattern' )

    factor = 1
    where = []
    fuzzymode = False
    positivematch = True

    # Since this is now searched for instead of matched on, we need to avoid
    # searching for e.g. "mail" in "e-mail".
    contextpatternxpathcontent = r'(?<![-#@;\/\\\+\=\:\.\$\*])' + manglepattern(
        contextpatternxpathcontent, 0 ) + r'(?![-#@\+\=\$\*])'

    if getattribute( contextpatternxpath, 'case' ) == 'keep':
        contextpattern = re.compile( contextpatternxpathcontent )
    else:
        contextpattern = re.compile( contextpatternxpathcontent, flags = re.I )

    if getattribute( contextpatternxpath, 'look' ) == 'before':
        factor = -1

    if getattribute( contextpatternxpath, 'mode' ) == 'fuzzy':
        fuzzymode = True

    if getattribute( contextpatternxpath, 'match' ) == 'negative':
        positivematch = False

    wherexpath = getattribute( contextpatternxpath, 'where' )
    if wherexpath:
        if fuzzymode:
            whererange = range( 1, ( int( wherexpath ) + 1 ) )
            for i in whererange:
                where.append( i * factor )
        else:
            where = [ ( int( wherexpath ) * factor ) ]
    else:
        where = [ ( 1 * factor ) ]

    return [ contextpattern, where, positivematch ]

def getattribute( element, attribute ):
    xpath = element.xpath( '@' + attribute )
    if xpath:
        return xpath[0]
    else:
        return None

def emptypatternmessage( element ):
    sys.exit( """Terminology: There is an empty {0} element.
Make sure each {0} element in the terminology file(s) contains a pattern.""".format(element) )

def xmlescape( text ):
    escapetable = {
        "&": "&amp;",
        '"': "&quot;",
        "'": "&apos;",
        ">": "&gt;",
        "<": "&lt;",
        }
    return "".join(escapetable.get(c,c) for c in text)

def termcheckmessage( acceptword, acceptcontext, word, line, content, contextid, basefile ):
    # FIXME: shorten content string (in the right place), to get closer toward
    # more focused results
    message = None
    content = xmlescape( content )

    filename = ""
    if basefile:
        filename = "<file>%s</file>" % str( basefile )

    withinid = ""
    if contextid:
        withinid = "<withinid>%s</withinid>" % str( contextid )

    message = etree.XML(  """<result>
            <place>%s%s<line>%s</line></place>
        </result>""" % ( filename, withinid, str( line ) ) )

    if acceptcontext:
        message.append( etree.XML( """<error>In the context of %s,
            do not use <quote>%s</quote>:
            <quote>%s</quote></error>""" % ( acceptcontext, word, content ) ) )
    else:
        message.append( etree.XML( """<error>Do not use
            <quote>%s</quote> here:
            <quote>%s</quote></error>""" % ( word, content ) ) )

    if acceptword:
        message.append( etree.XML( """<suggestion>Use <quote>%s</quote>
            instead.</suggestion>""" % acceptword ) )
    else:
        message.append( etree.XML( """<suggestion>Remove the word
            <quote>%s</quote>.</suggestion>""" % word ) )

    return message

def sentencelengthcheck( context, content, contentpretty, contextid, basefile ):
    messages = []

    if content:
        # I get this as a list with one lxml.etree._ElementUnicodeResult, not
        # as a list with a string.
        content = str( content[0] )

        if basefile:
            basefile = basefile[0]
        else:
            basefile = None

        if contextid:
            contextid = contextid[0]
        else:
            contextid = None

        # This if/else block should not be necessary (if there is content,
        # there should always also be pretty content, but that depends on the
        # XSLT used for checking). It hopefully won't hurt either.
        if contentpretty:
            contentpretty = str( contentpretty[0] )
        else:
            contentpretty = content

        sentences = sentencetokenizer( content )

        for sentence in sentences:
            words = sentence.split()
            wordcount = len( words )
            if wordcount >= 26:

                filename = ""
                if basefile:
                    filename = "<file>%s</file>" % str( basefile )

                withinid = ""
                if contextid:
                    withinid = "<withinid>%s</withinid>" % str( contextid )

                messagetype = 'warning'
                if wordcount >= 33:
                    messagetype = 'error'

                contentpretty = xmlescape( contentpretty )
                line = linenumber( context )
                messages.append( etree.XML( """<result>
                                <place>%s%s<line>%s</line></place>
                                <%s>Sentence with %s words:
                                <quote>%s</quote>
                            </%s>
                            <suggestion>Remove unnecessary words.</suggestion>
                            <suggestion>Split the sentence.</suggestion>
                        </result>""" % ( filename, withinid, str( line ),
                    messagetype, str( wordcount ), contentpretty, messagetype ) ) )

    return messages

def sentencetokenizer( text ):
    # FIXME: English hardcoded
    # Lookbehinds need to have a fixed length... thus _ca
    sentences = re.split( r'(?<![Ee]\.g|etc|[Ii]\.e| ca|n\.b|[Ii]nc)\.?\.?\.\s|!\s|\.?\.?\?\s', text )
    return sentences

def dupecheck( context, content, contentpretty, contextid, basefile ):
    global punctuationstart
    global punctuationend

    messages = []

    if content:
        # I get this as a list with one lxml.etree._ElementUnicodeResult, not
        # as a list with a string.
        content = str( content[0] )

        if basefile:
            basefile = basefile[0]
        else:
            basefile = None

        if contextid:
            contextid = contextid[0]
        else:
            contextid = None

        # This if/else block should not be necessary (if there is content,
        # there should always also be pretty content, but that depends on the
        # XSLT used for checking). It hopefully won't hurt either.
        if contentpretty:
            contentpretty = str( contentpretty[0] )
        else:
            contentpretty = content

        # FIXME: Find a clever way to be able to check for variants of the same
        # word, such as: a/an, singular/plural, verb tenses. It should ideally
        # not be hardcoded here.

        # FIXME: Get something better than s.split. Some existing tokenisers
        # are overzealous, such as the default one from NLTK.
        words = content.split()
        totalwords = len( words )

        if args.performance:
            timestartmatch = time.time()

        for wordposition, word in enumerate(words):
            if wordposition < 1:
                continue

            # FIXME: 000 is for when there is a large number separated by
            # spaces. Of course, putting it here is a hack, since separation
            # with spaces is somewhat language-specific.
            if word == "##@ignore##" or word == "000":
                continue

            wordstripped = replacepunctuation( word, 'end' )

            # FIXME: This implementation is a WTF and not especially extensible.
            # To its credit: it kinda works.
            if wordposition >= 5:
                if wordstripped == words[wordposition - 3]:
                    if ( words[wordposition - 1] != "##@ignore##" ) and ( words[wordposition - 2] != "##@ignore##" ):
                        if words[wordposition - 1] == words[wordposition - 4]:
                            firstwordstripped = replacepunctuation( words[wordposition - 5], 'start' )
                            if words[wordposition - 2] == firstwordstripped:
                                line = linenumber( context )
                                resultwords = words[wordposition - 2] + " " + words[wordposition - 1] + " " + wordstripped
                                messages.append( dupecheckmessage( resultwords,
                                    line, contentpretty, contextid, basefile ) )
                                continue

            if wordposition >= 3:
                if wordstripped == words[wordposition - 2]:
                    if words[wordposition - 1] != "##@ignore##":
                        firstwordstripped = replacepunctuation( words[wordposition - 3], 'start' )
                        if words[wordposition - 1] == firstwordstripped:
                            line = linenumber( context )
                            resultwords = words[wordposition - 1] + " " + wordstripped
                            messages.append( dupecheckmessage( resultwords,
                                line, contentpretty, contextid, basefile ) )
                            continue

            firstwordstripped = replacepunctuation( words[wordposition - 1], 'start' )
            if word == firstwordstripped:
                line = linenumber( context )
                messages.append( dupecheckmessage( wordstripped,
                    line, contentpretty, contextid, basefile ) )

        if args.performance:
            timeendmatch = time.time()
            timediffmatch = timeendmatch - timestartmatch
            print( """words: %s
time for this para: %s
average time per word: %s\n"""
                % ( str( totalwords ), str( timediffmatch ),
                    str( timediffmatch / (totalwords + .001 ) ) ) )

    return messages


def replacepunctuation( word, position ):
    # FIXME: Check if this really fares any better than a regular expression.
    punctuationstarts = [ "(","[","{" ]
    punctuationends = [ ")","]","}","/","\\",",",":",";","!","." ]

    if position == 'end':
        for punctuationend in punctuationends:
            if word.endswith( punctuationend ):
                word = word[:-1]
                break
    else:
        for punctuationstart in punctuationstarts:
            if word.startswith( punctuationstart ):
                word = word[1:]
                break
    return word

def dupecheckmessage( word, line, content, contextid, basefile ):
    content = xmlescape( content )

    filename = ""
    if basefile:
        filename = "<file>%s</file>" % str( basefile )

    withinid = ""
    # Python warns me: Use specific 'len(elem)' or 'elem is not None' test
    # instead.
    if contextid:
        withinid = "<withinid>%s</withinid>" % str( contextid )

    return etree.XML( """<result>
            <place>%s%s<line>%s</line></place>
            <error><quote>%s</quote> is duplicated:
                <quote>%s</quote>
            </error>
            <suggestion>Remove one instance of <quote>%s</quote>.</suggestion>
        </result>""" % ( filename, withinid, str(line), word, content, word ) )

def main():

    timestart = time.time()

    ns = etree.FunctionNamespace(
        'https://www.gitorious.org/style-checker/style-checker' )
    ns.prefix = 'py'
    ns.update( dict( linenumber = linenumber, termcheck = termcheck,
        buildtermdata = buildtermdata, dupecheck = dupecheck,
        sentencelengthcheck = sentencelengthcheck ) )

    location = os.path.dirname( os.path.realpath( __file__ ) )

    global args
    args = parseargs()

    if args.bookmarklet:
        webbrowser.open(
            os.path.join( location, '..', 'bookmarklet',
                'result-flagging-bookmarklet.html' ),
            new = 0 , autoraise = True )
        sys.exit()

    inputfilename = os.path.basename( args.inputfile.name )

    if args.outputfile:
        resultfilename = args.outputfile
        resultpath = os.path.dirname( os.path.realpath( args.outputfile ) )
    else:
        resultfilename = re.sub( r'(_bigfile)?\.xml', r'', inputfilename )
        resultfilename = '%s-stylecheck.xml' % resultfilename
        resultpath = os.path.dirname( os.path.realpath( args.inputfile.name ) )

    resultfile = os.path.join( resultpath, resultfilename )

    output = etree.XML(  """<?xml-stylesheet type="text/css" href="%s"?>
                            <results/>"""
                      % os.path.join( location, 'check.css' ) )

    rootelement = output.xpath( '/results' )

    resultstitle = etree.Element( 'results-title' )
    resultstitle.text = "Style Checker Results for %s" % inputfilename
    output.append( resultstitle )

    # Checking via XSLT
    parser = etree.XMLParser(   ns_clean = True,
                                remove_pis = False,
                                dtd_validation = False )
    inputfile = etree.parse( args.inputfile, parser )

    for checkfile in glob.glob( os.path.join(   location,
                                                'xsl-checks',
                                                '*.xslc' ) ):
        transform = etree.XSLT( etree.parse( checkfile, parser ) )
        result = transform( inputfile )

        if args.errors:
            # FIXME: The following could presumably also be done without adding
            # a separate stylesheet. Not sure if that would be any more
            # performant.
            errorstylesheet = os.path.join( location, 'errorsonly.xsl' )
            errortransform = etree.XSLT( etree.parse( errorstylesheet, parser ) )
            result = errortransform( result )

        result = result.getroot()

        if result.xpath( '/part/result' ):
            output.append( result )

    if not output.xpath( '/results/part' ):
        output.append( etree.XML(
             """<result>
                    <info>No problems detected.</info>
                    <suggestion>Celebrate!</suggestion>
                </result>""" ) )


    output.getroottree().write( resultfile,
                                xml_declaration = True,
                                encoding = 'UTF-8',
                                pretty_print = True )

    if args.show:
        webbrowser.open( resultfile, new = 0 , autoraise = True )

    printcolor( resultfile )
    if args.performance:
        print( "Total: " +  str( time.time() - timestart ) )


if __name__ == "__main__":
    main()
