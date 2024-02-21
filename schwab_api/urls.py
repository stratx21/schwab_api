
def homepage():
    return "https://www.schwab.com/"

def account_summary():
    return "https://client.schwab.com/clientapps/accounts/summary/"

def trade_ticket():
    return "https://client.schwab.com/app/trade/tom/#/trade"

# New API
def order_verification_v2(order_id = None):
    param = ("" if order_id == None else ("/"+str(order_id)))
    return "https://ausgateway.schwab.com/api/is.TradeOrderManagementWeb/v1/TradeOrderManagementWebPort/orders" + param

def account_info_v2():
    return "https://ausgateway.schwab.com/api/is.TradeOrderManagementWeb/v1/TradeOrderManagementWebPort/customer/accounts"

def positions_v2():
    return "https://ausgateway.schwab.com/api/is.Holdings/V1/Holdings/Holdings?=&includeCostBasis=true&includeRatings=true&includeUnderlyingOption=true"

def ticker_quotes_v2():
    return "https://ausgateway.schwab.com/api/is.TradeOrderManagementWeb/v1/TradeOrderManagementWebPort/market/quotes/list"

def orders_v2():
    return "https://ausgateway.schwab.com/api/is.TradeOrderStatusWeb/ITradeOrderStatusWeb/ITradeOrderStatusWebPort/orders/listView?DateRange=All&OrderStatusType=Open&SecurityType=AllSecurities&Type=All&ShowAdvanceOrder=true&SortOrder=Ascending&SortColumn=Status&CostMethod=M&IsSimOrManagedAccount=false&EnableDateFilterByActivity=true"

def todays_orders_v2(): # setting OrderStatusType to Open or Filled does not work. site uses all, and a local filter.
    return "https://ausgateway.schwab.com/api/is.TradeOrderStatusWeb/ITradeOrderStatusWeb/ITradeOrderStatusWebPort/orders/listView?DateRange=Today&OrderStatusType=All&SecurityType=AllSecurities&Type=All&ShowAdvanceOrder=true&SortOrder=Ascending&SortColumn=Status&CostMethod=M&IsSimOrManagedAccount=false&EnableDateFilterByActivity=true"

def cancel_order_v2():
    return "https://ausgateway.schwab.com/api/is.TradeOrderStatusWeb/ITradeOrderStatusWeb/ITradeOrderStatusWebPort/orders/cancelorder"

def transaction_history_v2():
    return "https://ausgateway.schwab.com/api/is.TransactionHistoryWeb/TransactionHistoryInterface/TransactionHistory/brokerage/transactions/export"

def replace_order_v2(order_id):
    return "https://ausgateway.schwab.com/api/is.TradeOrderManagementWeb/v1/TradeOrderManagementWebPort/orders/"+str(order_id)

# Old API
def positions_data():
    return "https://client.schwab.com/api/PositionV2/PositionsDataV2"

def order_verification():
    return "https://client.schwab.com/api/ts/stamp/verifyOrder"

def order_confirmation():
    return "https://client.schwab.com/api/ts/stamp/confirmorder"
