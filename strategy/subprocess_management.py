from schwab_api import Schwab
import strategy.spread_scraper_subprocess as spread_scraper_subprocess
from tools.terminal_colors import TermColor

import multiprocessing
from queue import Queue
import threading
import time


class SchwabManager():
    def __init__(self, account_id, api: Schwab):
        self.pipeWithApp, child_connection = multiprocessing.Pipe()
        self.subProcessManagerProcess = SchwabSubprocessesManager(child_connection, account_id, api)
        self.subProcessManagerProcess.start()
    
    def stopAll(self):
        print(TermColor.makeWarning("Sending STOP signal to subprocess manager process"))
        self.pipeWithApp.send({
            "command": "stopProcess",
        })
        self.subProcessManagerProcess.join()
        print(TermColor.makeWarning("subprocess manager process ended."))
    
    def spawn(
            self,
            ticker,
            profitMargin = 0.02,
            maintainedEquity = 1,
            minBASpread = 0.1,
            qty = 1,
            timeBeforeCancel = 3
    ): # returns True/False for success case 
        try:
            self.pipeWithApp.send({
                "command": "spawn",
                "ticker": ticker,
                "profitMargin": profitMargin,
                "maintainedEquity": maintainedEquity,
                "minBASpread": minBASpread,
                "qty": qty,
                "timeBeforeCancel": timeBeforeCancel
            })
            return True
        except Exception as e:
            print(TermColor.makeFail("[ERROR] failed to send data to pipe to spawn subprocess: " + str(e)))
            return False
    
    def stopTicker(self, ticker):
        print(TermColor.makeWarning(f'Sending STOP signal to subprocess for ticker {ticker}'))
        self.pipeWithApp.send({
            "command": "stopTicker",
            "ticker": ticker
        })
    
    def pollAppPipe(self):
        return self.pipeWithApp.poll()
    
    def receiveFromAppPipe(self):
        return self.pipeWithApp.recv()


class SubProcess():
    def __init__(self, process, pipeToSubprocess):
        self.process = process
        self.pipeToSubprocess = pipeToSubprocess
    
    def join(self):
        self.process.join()
    
    def send(self, package):
        self.pipeToSubprocess.send(package)


class SchwabSubprocessesManager(multiprocessing.Process):
    SLEEP_TIME = 2 # seconds
    TOKEN_UPDATE_TIME = 30 # seconds     (note: leave buffer time)

    def __init__(self, pipeWithDiscord, account_id, api: Schwab, **kwargs):
        super(SchwabSubprocessesManager, self).__init__()
        self.pipeWithDiscord = pipeWithDiscord
        self.daemon = False
        self.lastTokenUpdateTime = time.time()
        self.subprocesses: dict[str, SubProcess] = {}

        self.account_id = account_id
        self.api: Schwab = api

    def run(self):
        while True:
            try:
                if self.checkInputQueue():
                    return 
            except Exception as e:
                print(TermColor.makeFail("[ERROR] failed to check input queue in SchwabSubprocessesManager: " + e))
            self.refreshToken()
            time.sleep(SchwabSubprocessesManager.SLEEP_TIME)
    
    def refreshToken(self):
        # if time to refresh token 
        if time.time() - self.lastTokenUpdateTime >= SchwabSubprocessesManager.TOKEN_UPDATE_TIME:
            newTokenApi, newTokenUpdate = self.api.update_both_tokens()
            self.lastTokenUpdateTime = time.time()

            # send new token for each subprocess 
            for subprocess in self.subprocesses.values():
                subprocess.send({
                    "tokenApi": newTokenApi,
                    "tokenUpdate": newTokenUpdate,
                })

            print(TermColor.makeWarning("[DEBUG] token refreshed"))

    def checkInputQueue(self):
        # get info from queue - retrieve user input 
        while self.pipeWithDiscord.poll():
            fromQueue = self.pipeWithDiscord.recv()
            print(TermColor.makeWarning("[DEBUG] got data from queue. Data: " + str(fromQueue)))
            command = fromQueue["command"] # note - could have made each command its own key for the command info (good practice), but this is a little more performant 
            
            if command == "stopProcess": # signal processes to end, then end this thread 
                print(TermColor.makeWarning("[END] ending subprocesses..."))
                for subprocess in self.subprocesses.values():
                    subprocess.send({
                        "stopProcess": 0,
                    })
                for subprocess in self.subprocesses.values():
                    subprocess.join()
                print(TermColor.makeWarning("[END] all processess ended"))
                return 1 # end thread
        
            if command == "stopTicker": # stop process for ticker
                if "ticker" in fromQueue.keys():
                    ticker = fromQueue["ticker"]
                    if ticker in self.subprocesses.keys():
                        self.subprocesses[ticker].send({
                            "stopProcess": 0
                        })
                        self.subprocesses[ticker].join()
                        del self.subprocesses[ticker]
                    else: # ticker not in subprocesses
                        print(TermColor.makeFail("[ERROR] ticker not found in subprocesses for stopTicker command."))
                else:
                    print(TermColor.makeFail("[ERROR] ticker not found in data received for stopTicker command."))

            if command == "spawn": # spawn command 
                try:
                    ticker = fromQueue["ticker"]
                    profitMargin = fromQueue["profitMargin"]
                    maintainedEquity = fromQueue["maintainedEquity"]
                    minBASpread = fromQueue["minBASpread"]
                    qty = fromQueue["qty"]
                    timeBeforeCancel = fromQueue["timeBeforeCancel"]
                    if ticker in self.subprocesses.keys():
                        print(TermColor.makeFail("[ERROR] ticker \"" + ticker + "\" already exists in subprocesses!"))
                    else: # ticker does not yet exist in subprocesses dict 
                        # make new process
                        parent_connection, child_connection = multiprocessing.Pipe()
                        subprocess = multiprocessing.Process(
                            target=spread_scraper_subprocess.runSpreadScraperSubprocess,
                            args=[
                                child_connection,
                                self.api,
                                self.account_id,
                                ticker,
                                qty,
                                profitMargin,
                                minBASpread,
                                maintainedEquity,
                                timeBeforeCancel
                            ]
                        )
                        self.subprocesses[ticker] = SubProcess(subprocess, parent_connection)
                        subprocess.start()
                except Exception as e:
                    print(TermColor.makeFail("[ERROR] failed to spawn process in SchwabSubprocessesManager.checkInputQueue: " + str(e)))
        
        return 0