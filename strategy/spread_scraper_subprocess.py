import json
from queue import Queue
import threading
import time 

from tools.terminal_colors import TermColor
from tools import logger
from schwab_api import Schwab


LOOP_MINIMUM_RUNTIME = 1.5 # seconds


# global vars - shared with threads 
workingBuyOrderId = None
workingSellOrderId = None
currentEquity = 0


OVERSOLD_ERROR_PARTIAL_STRING = 'order may result in an oversold/overbought position' 


class ManageBuyThread(threading.Thread):

    def __init__(self, queue, args=(), kwargs=None):
        threading.Thread.__init__(self, args=(), kwargs=None)
        self.queue = queue
        self.daemon = True

        self.pipeWithDiscord = args[0]
        self.account_id = args[1]
        self.api: Schwab = args[2]
        self.ticker = args[3]
        self.qty = args[4]

    def run(self):
        global workingBuyOrderId
        global currentEquity
        while True:
            fromQueue = self.queue.get()
            if "buy" in fromQueue.keys():
                try:
                    messages, success, buyOrderId = self.api.trade_v2_buy_OCO_ONLY(
                        self.ticker,
                        qty=self.qty,
                        account_id=self.account_id,
                        limit_buy_price=fromQueue["buy"],
                        # usingTokenAutoUpdate=True
                    )
                    if success:
                        workingBuyOrderId = buyOrderId
                    else:
                        logger.logError("failed to send BUY. Messages: " + str(messages), self.ticker, self.pipeWithDiscord)
                except Exception as e:
                    logger.logError("error while sending BUY: " + str(e), self.ticker, self.pipeWithDiscord)

            if "cancel" in fromQueue.keys():
                messages, success = self.api.cancel_limit_order_v2(
                    self.account_id,
                    workingBuyOrderId,
                    self.ticker,
                    "Buy",
                    fromQueue["cancel"],
                    self.qty,
                    # usingTokenAutoUpdate=True
                )
                if success:
                    workingBuyOrderId = None
                else:
                    # failed to cancel BUY order
                    print(TermColor.makeWarning("[DEBUG] failed to cancel BUY order. Messages: " + str(messages)))
                    # assume it executed ( TODO IF executed ) 
                    messageCode = None
                    try:
                        messageCode = json.loads(messages[0])["Error"]["Code"]
                    except Exception as e:
                        print(TermColor.makeWarning("[DEBUG] error getting message code in ManageBuyThread cancel."))
                    if messageCode == None or messageCode != "UnsupportedApiVersion":
                        currentEquity += 1
                        workingBuyOrderId = None

            if "tokenApi" in fromQueue.keys():
                # print(TermColor.makeWarning("[DEBUG] updating api token in buy thread"))
                self.api.apiToken = fromQueue["tokenApi"]

            if "tokenUpdate" in fromQueue.keys():
                # print(TermColor.makeWarning("[DEBUG] updating update token in buy thread"))
                self.api.updateToken = fromQueue["tokenUpdate"]

            if "stopProcess" in fromQueue.keys():
                return

class ManageSellThread(threading.Thread):

    def __init__(self, queue, args=(), kwargs=None):
        threading.Thread.__init__(self, args=(), kwargs=None)
        self.queue = queue
        self.daemon = True

        self.pipeWithDiscord = args[0]
        self.account_id = args[1]
        self.api: Schwab = args[2]
        self.ticker = args[3]
        self.qty = args[4]

    def run(self):
        global workingSellOrderId
        global currentEquity
        while True:
            fromQueue = self.queue.get()
            if "sell" in fromQueue.keys():
                try:
                    messages, success, sellOrderId = self.api.trade_v2_sell_OCO_ONLY(
                        self.ticker,
                        qty=self.qty,
                        account_id=self.account_id,
                        limit_sell_price=fromQueue["sell"],
                        # usingTokenAutoUpdate=True
                    )
                    if success:
                        workingSellOrderId = sellOrderId
                    else:
                        if OVERSOLD_ERROR_PARTIAL_STRING in messages[0] or OVERSOLD_ERROR_PARTIAL_STRING in messages[1]:
                            logger.logError(f'failed to send SELL. Would cause negative position. current equity: {currentEquity}', self.ticker, self.pipeWithDiscord)
                        else:
                            logger.logError("failed to send SELL. Messages: " + str(messages), self.ticker, self.pipeWithDiscord)
                except Exception as e:
                    print(TermColor.makeFail("[ERROR] error while sending SELL: " + e))
            
            if "cancel" in fromQueue.keys():
                messages, success = self.api.cancel_limit_order_v2(
                    self.account_id,
                    workingSellOrderId,
                    self.ticker,
                    "Sell",
                    fromQueue["cancel"],
                    self.qty,
                    # usingTokenAutoUpdate=True
                )
                if success:
                    workingSellOrderId = None
                else:
                    # failed to cancel BUY order
                    # print(TermColor.makeWarning("[DEBUG] failed to cancel BUY order. Messages: " + str(messages)))
                    # assume it executed ( TODO IF executed ) 
                    messageCode = None
                    try:
                        messageCode = json.loads(messages[0])["Error"]["Code"]
                    except Exception as e:
                        print(TermColor.makeWarning("[DEBUG] error getting message code in ManageSellThread cancel."))
                    if messageCode == None or messageCode != "UnsupportedApiVersion":
                        currentEquity -= 1
                        workingSellOrderId = None

            if "tokenApi" in fromQueue.keys():
                self.api.apiToken = fromQueue["tokenApi"]

            if "tokenUpdate" in fromQueue.keys():
                self.api.updateToken = fromQueue["tokenUpdate"]

            if "stopProcess" in fromQueue.keys():
                return



def getBuySellPriceAdjustmentsFromProfitMargin(profitMargin): # returns   [buy adjustment, sell adjustment]
    if (profitMargin*100) % 2 == 0: # is an even number of cents
        return profitMargin/2.0, profitMargin/2.0
    else:
        # buy price adjusted if profitMargin is an odd number of cents
        return (profitMargin-0.01)/2.0 + 0.01, (profitMargin-0.01)/2.0



def runSpreadScraperSubprocess(
        pipeFromParent,   # read this pipe to hear from parent (subprocess manager)
        pipeWithDiscord,  # write to this pipe to write to discord
        api: Schwab,      # the API access
        account_id,
        ticker,           # stock ticker 
        qty,              # quantity of stock per order
        profitMargin,     # in dollars (ex: 0.02 for 2 cents)
        minBASpread,      # minimum diff between Ask-Bid required to initiate trade (in dollars)
        maintainedEquity, # count of shares at start. Will  try to maintain this number. Used to allow quick sells while holding.
        timeBeforeCancel  # time before cancel order is sent (in seconds)
):
    print(TermColor.makeWarning("[WARNING] NOTE condition: need " + str(maintainedEquity) + " shares before start.."))

    # price adjustments setup 
    buyPriceAdjustment, sellPriceAdjustment = getBuySellPriceAdjustmentsFromProfitMargin(profitMargin)
    
    isStopping = False

    # setup usable vars 
    global currentEquity 
    currentEquity = maintainedEquity
    global workingBuyOrderId
    global workingSellOrderId

    # setup buy and sell threads 
    buyThread = ManageBuyThread(Queue(), args=(pipeWithDiscord, account_id, api, ticker, qty))
    buyThread.start()
    sellThread = ManageSellThread(Queue(), args=(pipeWithDiscord, account_id, api, ticker, qty))
    sellThread.start()

    ######################################################################################
    # loop process:
    while True:
        loopStartTime = time.time()

        #############################################################
        # check for data in pipe 
        while pipeFromParent.poll():
            try:
                fromPipe = pipeFromParent.recv()

                if "tokenApi" in fromPipe.keys():
                    newToken = fromPipe["tokenApi"]
                    api.apiToken = newToken
                    buyThread.queue.put({
                        "tokenApi": newToken
                    })
                    sellThread.queue.put({
                        "tokenApi": newToken
                    })

                if "tokenUpdate" in fromPipe.keys():
                    newToken = fromPipe["tokenUpdate"]
                    api.updateToken = newToken
                    buyThread.queue.put({
                        "tokenUpdate": newToken
                    })
                    sellThread.queue.put({
                        "tokenUpdate": newToken
                    })

                if "stopProcess" in fromPipe.keys():
                    isStopping = True
                
            except Exception as e:
                logger.logError("failed receing data from pipe, under ticker \"" + ticker + "\": " + str(e), ticker, pipeWithDiscord)
    
        # stop process if done 
        if isStopping and currentEquity == maintainedEquity and workingBuyOrderId == None and workingSellOrderId == None:
            print(TermColor.makeWarning("[END] ending buy and sell threads..."))

            buyThread.queue.put({
                "stopProcess": 0,
            })
            sellThread.queue.put({
                "stopProcess": 0,
            })
            buyThread.join()
            print(TermColor.makeWarning(f'[END] {ticker} BUY thread ended'))
            sellThread.join()
            print(TermColor.makeWarning(f'[END] {ticker} SELL thread ended'))
            pipeWithDiscord.send({
                "stopProcessSuccess": ticker
            })
            return

        #############################################################
        # manage scraping trades 
        
        # get quote 
        try:
            bid, ask = api.getBidAsk(
                ticker,
                account_id,
                # usingTokenAutoUpdate=True
            )
            avgOfSpread = round((ask + bid)/2, 2)
            
            newBuyPrice = avgOfSpread - buyPriceAdjustment
            newSellPrice = avgOfSpread + sellPriceAdjustment

            # if (should NOT initiate new scrape trade, due to BA spread being too small): then sleep and skip 
            if currentEquity == maintainedEquity and ask - bid < minBASpread:
                timeToSleep = LOOP_MINIMUM_RUNTIME/2 - (time.time() - loopStartTime) # force loop iteration to half of the normal time 
                if timeToSleep > 0:
                    time.sleep(timeToSleep) 
                continue
            
            investmentStartTime = time.time()

            # send sell 
            if ((isStopping and currentEquity > maintainedEquity) or ((not isStopping) and currentEquity > 0)) and workingSellOrderId == None:
                print(TermColor.makeWarning("[DEBUG] sending sell (eq=" + str(currentEquity) + ")..."))  
                sellThread.queue.put({
                    "sell": newSellPrice,
                })
                # try:
                #     messages, success, sellOrderId = api.trade_v2_limit_sell_order(
                #         ticker,
                #         qty=qty,
                #         account_id=account_id,
                #         limit_price=newSellPrice,
                #         usingTokenAutoUpdate=True
                #     )
                #     if success:
                #         workingSellOrderId = sellOrderId
                #     else:
                #         print(TermColor.makeFail("[ERROR] failed to send SELL. Messages: " + str(messages)))
                # except Exception as e:
                #     print(TermColor.makeFail("[ERROR] error while sending SELL: " + e))


            # send buy 
            if ((isStopping and currentEquity < maintainedEquity) or ((not isStopping) and currentEquity <= maintainedEquity)) and workingBuyOrderId == None:
                print(TermColor.makeWarning("[DEBUG] sending buy (eq=" + str(currentEquity) + ")..."))
                buyThread.queue.put({
                    "buy": newBuyPrice,
                })
                # try:
                #     messages, success, buyOrderId = api.trade_v2_limit_buy_order(
                #         ticker,
                #         qty=qty,
                #         account_id=account_id,
                #         limit_buy_price=newBuyPrice,
                #         usingTokenAutoUpdate=True
                #     )
                #     if success:
                #         workingBuyOrderId = buyOrderId
                #     else:
                #         print(TermColor.makeFail("[ERROR] failed to send BUY. Messages: " + str(messages)))
                # except Exception as e:
                #     print(TermColor.makeFail("[ERROR] error while sending BUY: " + e))


            # DELAY
            # TODO could use new quote - if the stock is moving fast, time won't work well 
            secondsInvested = time.time() - investmentStartTime
            if secondsInvested > timeBeforeCancel:
                time.sleep(timeBeforeCancel - secondsInvested)

            # cancel buy 
            if workingBuyOrderId != None:
                buyThread.queue.put({
                    "cancel": newBuyPrice,
                })
                # messages, success = api.cancel_limit_order_v2(
                #     account_id,
                #     workingBuyOrderId,
                #     ticker,
                #     "Buy",
                #     newBuyPrice,
                #     qty,
                #     usingTokenAutoUpdate=True
                # )
                # if success:
                #     workingBuyOrderId = None
                # else:
                #     # failed to cancel BUY order
                #     print(TermColor.makeWarning("[DEBUG] failed to cancel BUY order. Messages: " + str(messages)))
                #     # assume it executed ( TODO IF executed ) 
                #     currentEquity += 1
                #     workingBuyOrderId = None

            # cancel sell 
            if workingSellOrderId != None:
                sellThread.queue.put({
                    "cancel": newSellPrice,
                })
                # messages, success = api.cancel_limit_order_v2(
                #     account_id,
                #     workingSellOrderId,
                #     ticker,
                #     "Sell",
                #     newSellPrice,
                #     qty,
                #     usingTokenAutoUpdate=True
                # )
                # if success:
                #     workingSellOrderId = None
                # else:
                #     # failed to cancel BUY order
                #     print(TermColor.makeWarning("[DEBUG] failed to cancel BUY order. Messages: " + str(messages)))
                #     # assume it executed ( TODO IF executed ) 
                #     currentEquity -= 1
                #     workingSellOrderId = None


        except Exception as e:
            logger.logError("failed managing scraping trades: " + str(e), ticker, pipeWithDiscord)
        


        #####################
        # runtime management 
        timeDiffSecs = time.time() - loopStartTime
        print(TermColor.makeWarning("[DEBUG] scraper subprocess iteration runtime: " + str(timeDiffSecs/1000.0) + " ms"))
        if timeDiffSecs < LOOP_MINIMUM_RUNTIME:
            time.sleep(LOOP_MINIMUM_RUNTIME - timeDiffSecs)
        



"""
    ideas:
        - DONE can stick buy and sell order management in threads 

"""

