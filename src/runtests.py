#! /usr/bin/env python2.4

helpText = '''Run the automatic integration test facility.

The specified directory is assumed to contain EPICS modules. Each module
is inspected, if it contains a dls/test subdirectory this is taken
as an indication that the module supports the test system and any Python
scripts in this directory are executed.

Options:
   -h             Print this help text and exit.
   -m <module>    Execute only the tests for the module specified.
   -b             Build the module before executing tests.
   -i             Run the IOC before executing the tests.
   -s <directory> The directory to search, defaults to ".".
   -d <level>     Diagnostic output level.
   -t <target>    Execute only tests for the named target.
   -c <case>      Execute only the specified test.
   -f <file>      Read a configuration file.
   -g             Run the GUI commands before the tests.
   -q             Log output from test execution.
   -p <processes> The number of tests to run in parallel, default 1.
   -l <name>      Create a summary log file.
'''

import os, sys, subprocess, thread, socket, select

class RunTests(object):

    defaultConfig = '''export EDMOBJECTS=/dls_sw/epics/R3.14.8.2/extensions/templates/edm
    export EDMPVOBJECTS=/dls_sw/epics/R3.14.8.2/extensions/templates/edm
    export EDMFILES=/dls_sw/epics/R3.14.8.2/extensions/templates/edm
    export EDMLIBS=/dls_sw/epics/R3.14.8.2/extensions/lib/linux-x86
    export EDMHELPFILES=/dls_sw/epics/R3.14.8.2/extensions/html/edm
    export EPICS_CA_MAX_ARRAY_BYTES=1000000
    '''
    
    def __init__(self):
        # Get the command line arguments
        self.module = None
        self.target = None
        self.testCase = None
        self.build = False
        self.runIoc = False
        self.logOutput = False
        self.runGui = False
        self.searchDirectory = "."
        self.diagnosticLevel = 0
        self.serverSocketName = None
        self.exports = []
        self.configFile = ""
        self.resultServerCount = 0
        self.numTestProcesses = 1
        self.runTestThreads = {}
        self.resultProcessThreads = {}
        self.summaryLogFile = None
        if self.processArguments():
            self.useConfigFile()
            # Create some lock objects
            self.getCmdLock = thread.allocate_lock()
            self.logFileLock = thread.allocate_lock()
            self.resultsLock = thread.allocate_lock()
            # Start the results server thread
            self.resultServer = thread.start_new_thread(self.resultServer, ())
            # Get the command list
            self.testCommands = []
            self.determineTestCommands()
            # Start the execution threads
            for i in range(self.numTestProcesses):
                lock = thread.allocate_lock()
                lock.acquire()
                t = thread.start_new_thread(self.runTest, (lock,))
                self.runTestThreads[t] = lock
            # Now wait until they are complete
            for t, lock in self.runTestThreads.iteritems():
                lock.acquire()
            for t, lock in self.runTestThreads.iteritems():
                lock.release()
            # Now wait until the result processing threads are complete
            for t, lock in self.resultProcessThreads.iteritems():
                lock.acquire()
            for t, lock in self.resultProcessThreads.iteritems():
                lock.release()

    def getTestCmd(self):
        '''Returns the next test command to run.'''
        result = None
        self.getCmdLock.acquire()
        if len(self.testCommands) > 0:
            result = self.testCommands[0]
            self.testCommands = self.testCommands[1:]
        self.getCmdLock.release()
        return result;

    def runTest(self, lock):
        '''This function runs tests until no more remain.  It is
        designed to run as a seperate thread.'''
        cmd = self.getTestCmd()
        while cmd is not None:
            p = subprocess.Popen(cmd[0], cwd=cmd[1], shell=True)
            p.wait()
            cmd = self.getTestCmd()
        lock.release()
        
    def determineTestCommands(self):
        '''Scans the modules and builds a list containing the commands that
        should be run to execute the test suites.'''
        # For each entry in the search directory...
        modules = os.listdir(self.searchDirectory)
        for module in modules:
            # Is there a test directory?
            moduleDir = self.searchDirectory + '/' + module
            testDir = moduleDir + '/dls/test'
            if os.path.isdir(testDir):
                # Is this a module we should be testing?
                if self.module is None or self.module == module:
                    # Execute any python scripts in this directory
                    files = os.listdir(testDir)
                    for file in files:
                        fileParts = os.path.splitext(file)
                        if fileParts[1] == '.py':
                            #path = testDir + '/' + file
                            #log = testDir + '/' + fileParts[0] + '.log'
                            path = './dls/test/' + file
                            log = './dls/test/' + fileParts[0] + '.log'
                            options = "-d %s" % self.diagnosticLevel
                            if self.build:
                                options += " -b"
                            if self.runIoc:
                                options += " -i"
                            if self.runGui:
                                options += " -g"
                            if self.target is not None:
                                options += " -t "
                                options += self.target
                            if self.testCase is not None:
                                options += " -c "
                                options += self.testCase
                            if self.serverSocketName is not None:
                                options += " -r "
                                options += self.serverSocketName
                            cmd = ""
                            for export in self.exports:
                                cmd += export + " "
                            cmd += "%s %s" % (path, options)
                            if self.logOutput:
                                cmd += " &> %s" % (log)
                            self.testCommands.append((cmd, moduleDir))
    
    def processArguments(self):
        """Process the command line arguments.
        """
        result = True
        state = "none"
        for arg in sys.argv:
            if state == "none":
                if arg == "-m":
                    state = "module"
                elif arg == "-s":
                    state = "directory"
                elif arg == "-d":
                    state = "diagnostic"
                elif arg == "-t":
                    state = "target"
                elif arg == "-c":
                    state = "case"
                elif arg == "-f":
                    state = "configFile"
                elif arg == "-p":
                    state = "processes"
                elif arg == "-l":
                    state = "logFile"
                elif arg == "-b":
                    self.build = True
                elif arg == "-i":
                    self.runIoc = True
                elif arg == "-g":
                    self.runGui = True
                elif arg == "-q":
                    self.logOutput = True
                elif arg == "-h":
                    print helpText
                    result = False
            elif state == "module":
                self.module = arg
                state = "none"
            elif state == "target":
                self.target = arg
                state = "none"
            elif state == "case":
                self.testCase = arg
                state = "none"
            elif state == "directory":
                self.searchDirectory = arg
                state = "none"
            elif state == "diagnostic":
                self.diagnosticLevel = int(arg)
                state = "none"
            elif state == "processes":
                self.numTestProcesses = int(arg)
                state = "none"
            elif state == "configFile":
                self.configFile = arg
                state = "none"
            elif state == "logFile":
                self.summaryLogFile = arg
                state = "none"
            else:
                state = "none"
        return result
        
    def resultServer(self):
        """This function contains the results server thread.  It's only
        task is to respond to connects on the server socket, spawning a
        further result processing thread for each results client."""
        self.serverSocketName = os.getcwd() + "/resultServer"
        try:
            os.remove(self.serverSocketName)
        except:
            pass
        serverSocket = socket.socket(socket.AF_UNIX)
        serverSocket.bind((self.serverSocketName))
        serverSocket.listen(5)
        while True:
            select.select([serverSocket],[],[])
            connection = serverSocket.accept()
            lock = thread.allocate_lock()
            lock.acquire()
            client = thread.start_new_thread(self.processResults, (connection[0],lock))
            self.resultProcessThreads[client] = lock

    def processResults(self, clientSocket, lock):
        """Processes the TAP stream from a single client test suite."""
        self.resultsLock.acquire()
        self.resultServerCount += 1
        myId = self.resultServerCount
        self.resultsLock.release()
        tempFile = None
        tempFileName = "%s.%s"%(self.summaryLogFile, myId)
        if self.summaryLogFile is not None:
            tempFile = open(tempFileName, "w+")
        going = True
        while going:
            text = clientSocket.recv(4096)
            if len(text) > 0:
                if tempFile is not None:
                    tempFile.write(text)
                if self.logOutput:
                    lines = text.split('\n')
                    for line in lines:
                        if len(line) > 0:
                            print "[%s] %s" % (myId, line)
            else:
                going = False
        # If we have stored the output in a temporary file, now copy it
        # onto the end of the full log file.
        if tempFile is not None:
            tempFile.close()
            self.logFileLock.acquire()
            logFile = open(self.summaryLogFile, "a+")
            tempFile = open(tempFileName, "r")
            for line in tempFile:
                logFile.write(line)
            logFile.close()
            tempFile.close()
            self.logFileLock.release()
        lock.release()
        
    def useConfigFile(self):
        """Parse the config file and record the configuration."""
        try:
            rFile = open(self.configFile, "r")
        except IOError:
            for line in RunTests.defaultConfig.split('\n'):
                self.useConfigLine(line)
        else:
            for line in rFile:
                self.useConfigLine(line)

    def useConfigLine(self, line):
        '''Parse a single configuration line.'''
        g = line.strip().split(' ', 1)
        if len(g) > 0:
            if g[0] == "export" and len(g) == 2:
                self.exports.append(g[1].strip())
            elif g[0] == "search" and len(g) == 2:
                self.searchDirectory = g[1].strip()
            elif g[0] == "processes" and len(g) == 2:
                self.numTestProcesses = int(g[1].strip())

if __name__ == "__main__":
    tests = RunTests()
