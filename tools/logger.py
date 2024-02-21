from tools.terminal_colors import TermColor
import datetime

def logError(errstr, ticker, pipeWithDiscord = None, includePrint=True):
    if pipeWithDiscord != None:
        pipeWithDiscord.send({
            "error": errstr,
            "ticker": ticker
        })
    if includePrint:
        print(TermColor.makeFail(f'[ERROR] [{datetime.datetime.now().strftime("%I:%M:%S%p on %D")}] [{ticker}] {errstr}'))


def logRareError(errstr, ticker, pipeWithDiscord = None, includePrint=True):
    if pipeWithDiscord != None:
        pipeWithDiscord.send({
            "rareError": errstr,
            "ticker": ticker
        })
    if includePrint:
        tickerstr = "" if ticker == None else f' [{ticker}]' 
        print(TermColor.makeFail(f'[RARE ERROR]{tickerstr} {errstr}'))
