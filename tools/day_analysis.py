from schwab_api import Schwab
import json
from tools.terminal_colors import TermColor

def printStat(buyPrice, sellPrice, isMarket, totalProfit):
    print("%.2f" % round(buyPrice, 2), end=" | ")
    print("%.2f" % round(sellPrice, 2), end=" ||| ")
    profit = sellPrice - buyPrice
    print(TermColor.GREEN if profit >= 0 else TermColor.FAIL, end="")
    print("%.2f" % round(profit, 2), end=" ")
    print(TermColor.ENDC, end="")
    print(" :: total: ", end="")
    print("%.2f" % round(totalProfit, 2), end="")
    print("    (market)" if isMarket else "")

def printDayAnalysis(api: Schwab, account_id: str, stockTicker: str):
    buysQueue = []
    extraSell = None
    totalProfit = 0.00 # TODO profit currently does not adjust for QTY > 1
    try:
        try:
            orders, success = api.todays_orders_v2(account_id)
        except Exception as e:
            print("EEEEEEEEEEEE", e)
        for order in orders:
            try:
                orderItem = order["OrderList"][0]
                # orderId = orderItem["OrderId"]
                if orderItem["OrderStatus"] == "Filled" and orderItem["DisplaySymbol"] == stockTicker:
                    try:
                        if orderItem["OrderAction"] == "Buy": # is a buy order
                            try:
                                fillPrice = float(orderItem["FillPrice"].replace('$',''))
                                if extraSell == None:
                                    buysQueue.append(fillPrice)
                                else:
                                    totalProfit += extraSell - fillPrice
                                    printStat(fillPrice, extraSell, "Limit" not in orderItem["Price"], totalProfit)
                                    extraSell = None
                            except Exception as e:
                                print("CCCCCCCCCCC", e)
                        elif orderItem["OrderAction"] == "Sell": # is a sell order
                            try:
                                fillPrice = float(orderItem["FillPrice"].replace('$',''))
                                if len(buysQueue) > 0:
                                    buyPrice = buysQueue.pop()
                                    totalProfit += fillPrice - buyPrice
                                    printStat(buyPrice, fillPrice, "Limit" not in orderItem["Price"], totalProfit)
                                else:
                                    extraSell = fillPrice
                            except Exception as e:
                                print("DDDDDDD", e)
                    except Exception as e:
                        print("BBBBBBBBBBB", e)
            except Exception as e:
                print("AAAAAA ", e)

                
        
    
        with open('temp.json', 'w', encoding='utf-8') as f:
            json.dump(orders, f, ensure_ascii=False, indent=4)
            
    except Exception as ex:
        print(TermColor.FAIL + "==========================")
        print("[ERROR] ERROR in getting orders..")
        print(ex)
        print("==========================" + TermColor.ENDC)
    
    



    print("bye bye")



if __name__ == '__main__':
    # Initialize our schwab instance
    api = Schwab()

    # Login using playwright
    print("Logging into Schwab")
    logged_in = api.login(
        #username=USERNAME,
        #password=password,
        #totp_secret=totp_secret # Get this by generating TOTP at https://itsjafer.com/#/schwab
    )

    account_id = "75218588"
    stockTicker = input("enter stock ticker: ")
    print("stock ticker: \"" + stockTicker + "\"")

    printDayAnalysis(api, account_id, stockTicker)

