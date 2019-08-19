import os
import sys
import json
import jsonpickle
from subprocess import Popen, PIPE
import ast
from itertools import takewhile, dropwhile
import glob
from multiprocessing import cpu_count
import re
import signal
from contextlib import contextmanager

@contextmanager
def timeout(time):
    # Register a function to raise a TimeoutError on the signal.
    signal.signal(signal.SIGALRM, lambda: sys.exit(2))
    # Schedule the signal to be sent after ``time``.
    signal.alarm(time)
    yield

defaultTimeout = 16 * 60
def getTimeout(timeoutString):
    l = timeoutString.split()
    if len(l) != 2 or not l[0].isdigit():
        return defaultTimeout
    elif l[1] == "second" or l[1] == "seconds":
        return int(l[0])
    elif l[1] == "minute" or l[1] == "minutes":
        return int(l[0]) * 60
    elif l[1] == "hour" or l[1] == "hours":
        return int(l[0]) * 60 * 60
    else:
        return defaultTimeout

class Result:
    def __init__(self, filename, message, patternId, line):
        self.filename = filename
        self.message = message
        self.patternId = patternId
        self.line = line
    def __str__(self):
        return f'Result({self.filename},{self.message},{self.patternId},{self.line})'
    def __repr__(self):
        return self.__str__()
    def __eq__(self, o):
        return self.filename == o.filename and self.message == o.message and self.patternId == o.patternId and self.line == o.line

def toJson(obj): return jsonpickle.encode(obj, unpicklable=False)

def readJsonFile(path):
    with open(path, 'r') as file:
        res = json.loads(file.read())
    return res

def runPylint(options, files):
    process = Popen(
        ['python3', '-m','pylint'] + options + files,
        stdout=PIPE
    )
    stdout = process.communicate()[0]
    return stdout.decode('utf-8')

def isPython3(f):
    try:
        with open(f, 'r') as stream:
            try:
                ast.parse(stream.read())
            except (ValueError, TypeError, UnicodeError):
                # Assume it's the current interpreter.
                return True
            except SyntaxError:
                # the other version or an actual syntax error on current interpreter
                return False
            else:
                return True
    except Exception:
        # Shouldn't happen, but if it does, just assume there's
        # something inherently wrong with the file.
        return True

def parseMessage(message):
    return re.search('''\[(.+)\(.+\] (.+)''', message).groups()

def parseResult(res):
    lines = res.split(os.linesep)
    splits = [arr for arr in [[split.strip() for split in l.split(':')] for l in lines] if len(arr) == 3]
    def createResults():
        for res in splits:
            (patternId, message) = parseMessage(res[2])
            yield Result(filename=res[0],message=message,patternId=patternId,line=int(res[1], 10))
    return list(createResults())

def walkDirectory(directory):
    def generate():
        for filename in glob.iglob(directory + '**/*.py', recursive=True):
            res = filename[len(os.path.abspath(directory)) + 1:1]
            yield res
    return list(generate())

def readConfiguration(configFile, srcDir):
    def allFiles(): return walkDirectory(srcDir)
    try:
        configuration = readJsonFile(configFile)
        files = [f for f in configuration['files']] if 'files' in configuration else allFiles()
        tools = [t for t in configuration['tools'] if t['name'] == 'PyLint (Python 3)']
        if len(tools) > 0:
            pylint = tools[0]
            rules = ['--disable=all','--enable=' + ','.join([p['patternId'] for p in pylint['patterns']])] if 'patterns' in pylint else []
        else:
            rules = []
        rules = ['--disable=all','--enable=' + ','.join([p['patternId'] for p in pylint['patterns']])] if 'patterns' in pylint else []
    except:
        rules = []
        files = allFiles()
    return rules, [f for f in files if isPython3(f)]

def chunks(lst,n):
    return [lst[i:i + n] for i in range(0, len(lst), n)]

def runPylintWith(rules, files):
    res = runPylint([
        '--output-format=parseable',
        '--load-plugins=pylint_django',
        '--disable=django-installed-checker,django-model-checker',
        '--load-plugins=pylint_flask',
        '-j',
        str(cpu_count())] +
        rules,
        files)
    return parseResult(res)

def runTool(configFile, srcDir):
    (rules, files) = readConfiguration(configFile, srcDir)
    res = []
    filesWithPath = [f'{srcDir}/{f}' for f in files]
    for chunk in chunks(filesWithPath, 10):
        res.extend(runPylintWith(rules, chunk))
    for result in res:
        if result.filename.startswith(srcDir + '/'):
            result.filename = result.filename[len(srcDir) + 1:]
    return res

def resultsToJson(results):
    return os.linesep.join([toJson(res) for res in results])

if __name__ == '__main__':
    with timeout(getTimeout(os.environ['TIMEOUT'])):
        try:
            results = runTool('/.codacyrc', '/src')
            print(resultsToJson(results))
        except:
            sys.exit(1)