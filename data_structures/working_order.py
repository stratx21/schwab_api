
MAX_REPLACEMENT_ATTEMPTS = 5

class WorkingOrder:
    def __init__(self, account_id, ticker, isBuy, limitPrice, orderId): # TODO add qty
        """
            The WorkingOrder class. Used to store working order data.

        """
        self.account_id = account_id
        self.ticker = ticker
        self.isBuy = isBuy
        self.limitPrice = limitPrice
        self.replacementAttempts = 0
        self.isFilled = False

        self.orderId = orderId

        # TODO deprecate these 
        self.buyOrderId = orderId
        self.sellOrderId = None
