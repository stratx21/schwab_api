import datetime
import json
import urllib.parse
import requests

from . import urls
from .account_information import Position, Account
from .authentication import SessionManager
import time

REQUEST_TIMEOUT = 5 # seconds

class Schwab(SessionManager):
    def __init__(self, **kwargs):
        """
            The Schwab class. Used to interact with schwab.

        """
        self.headless = kwargs.get("headless", True)
        self.browserType = kwargs.get("browserType", "firefox")
        self.headers = {}
        self.lastTimeTokenUpdated = None
        self.apiToken = None
        self.updateToken = None
        super(Schwab, self).__init__()

    def get_account_info(self):
        """
            Returns a dictionary of Account objects where the key is the account number
        """

        account_info = dict()
        # In order for this to return info for all accounts, the web interface excludes the
        # AcctInfo cookie and sets the CustAccessInfo cookie to a value like:
        # '<something>|<some_acct_num>|AllAccts'
        # instead of:
        # '<something>|<some_acct_num>|'
        # There can be multiple cookies with the same name but having different attributes,
        # i.e. domains '' and '.schwab.com', so we need to be careful when deleting or modifying
        # cookies with a certain name
        requests.cookies.remove_cookie_by_name(self.session.cookies, 'AcctInfo')
        for cookie in self.session.cookies:
            if cookie.name == 'CustAccessInfo':
                if cookie.value.endswith('|'):
                    cookie.value += 'AllAccts'
                    self.session.cookies.set_cookie(cookie)
        r = self.session.get(urls.positions_data())
        response = json.loads(r.text)
        for account in response['Accounts']:
            positions = list()
            for security_group in account["SecurityGroupings"]:
                for position in security_group["Positions"]:
                    positions.append(
                        Position(
                            position["DefaultSymbol"],
                            position["Description"],
                            float(position["Quantity"]),
                            float(position["Cost"]),
                            float(position["MarketValue"])
                        )._as_dict()
                    )

                    if not "ChildOptionPositions" in position:
                        continue

                    # Add call positions if they exist
                    for child_position in position["ChildOptionPositions"]:
                        positions.append(
                            Position(
                                child_position["DefaultSymbol"],
                                child_position["Description"],
                                float(child_position["Quantity"]),
                                float(child_position["Cost"]),
                                float(child_position["MarketValue"])
                            )._as_dict()
                        )
            account_info[int(account["AccountId"])] = Account(
                account["AccountId"],
                positions,
                account["Totals"]["MarketValue"],
                account["Totals"]["CashInvestments"],
                account["Totals"]["AccountValue"],
                account["Totals"]["Cost"],
            )._as_dict()

        return account_info

    def get_transaction_history_v2(self, account_id):
        """
            account_id (int) - The account ID to place the trade on. If the ID is XXXX-XXXX,
                        we're looking for just XXXXXXXX.

            Returns a dictionary of transaction history entries for the provided account ID.
        """

        data = {
            "timeFrame": "All",
            "selectedTransactionTypes": [
                "Adjustments",
                "AtmActivity",
                "BillPay",
                "CorporateActions",
                "Checks",
                "Deposits",
                "DividendsAndCapitalGains",
                "ElectronicTransfers",
                "Fees",
                "Interest",
                "Misc",
                "SecurityTransfers",
                "Taxes",
                "Trades",
                "VisaDebitCard",
                "Withdrawals"
            ],
            "exportType": "Json",
            "selectedAccountId": str(account_id),
            "sortColumn": "Date",
            "sortDirection": "Descending"
        }
        r = requests.post(urls.transaction_history_v2(), json=data, headers=self.headers)
        if r.status_code != 200:
            return [r.text], False
        return json.loads(r.text)

    def trade(self, ticker, side, qty, account_id, dry_run=True):
        """
            ticker (Str) - The symbol you want to trade,
            side (str) - Either 'Buy' or 'Sell',
            qty (int) - The amount of shares to buy/sell,
            account_id (int) - The account ID to place the trade on. If the ID is XXXX-XXXX,
                         we're looking for just XXXXXXXX.

            Returns messages (list of strings), is_success (boolean)
        """

        if side == "Buy":
            buySellCode = 1
        elif side == "Sell":
            buySellCode = 2
        else:
            raise Exception("side must be either Buy or Sell")

        data = {
            "IsMinQty":False,
            "CustomerId":str(account_id),
            "BuySellCode":buySellCode,
            "Quantity":str(qty),
            "IsReinvestDividends":False,
            "SecurityId":ticker,
            "TimeInForce":"1", # Day Only
            "OrderType":1, # Market Order
            "CblMethod":"FIFO",
            "CblDefault":"FIFO",
            "CostBasis":"FIFO",
            }

        r = self.session.post(urls.order_verification(), data)

        if r.status_code != 200:
            return [r.text], False

        response = json.loads(r.text)

        messages = list()
        for message in response["Messages"]:
            messages.append(message["Message"])

        if dry_run:
            return messages, True

        data = {
            "AccountId": str(account_id),
            "ActionType": side,
            "ActionTypeText": side,
            "BuyAction": side == "Buy",
            "CostBasis": "FIFO",
            "CostBasisMethod": "FIFO",
            "IsMarketHours": True,
            "ItemIssueId": int(response['IssueId']),
            "NetAmount": response['NetAmount'],
            "OrderId": int(response["Id"]),
            "OrderType": "Market",
            "Principal": response['QuoteAmount'],
            "Quantity": str(qty),
            "ShortDescription": urllib.parse.quote_plus(response['IssueShortDescription']),
            "Symbol": response["IssueSymbol"],
            "Timing": "Day Only"
        }

        r = self.session.post(urls.order_confirmation(), data)

        if r.status_code != 200:
            messages.append(r.text)
            return messages, False

        response = json.loads(r.text)
        if response["ReturnCode"] == 0:
            return messages, True

        return messages, False

    def trade_v2(self,
        ticker,
        side,
        qty,
        account_id,
        dry_run=True,
        # The Fields below are experimental fields that should only be changed if you know what you're doing.
        order_type=49,
        duration=48,
        limit_price=0,
        stop_price=0,
        primary_security_type=46,
        valid_return_codes = {0,10},
        affirm_order=False,
        costBasis='FIFO'
        ):
        """
            ticker (Str) - The symbol you want to trade,
            side (str) - Either 'Buy' or 'Sell',
            qty (int) - The amount of shares to buy/sell,
            account_id (int) - The account ID to place the trade on. If the ID is XXXX-XXXX,
                        we're looking for just XXXXXXXX.
            order_type (int) - The order type. This is a Schwab-specific number, and there exists types
                        beyond 49 (Market) and 50 (Limit). This parameter allows setting specific types
                        for those willing to trial-and-error. For reference but not tested: 
                        49 - Market
                        50 - Limit
                        51 - Stop market
                        52 - Stop limit
                        84 - Trailing stop
                        53 - Market on close
            duration (int) - The duration type for the order. For now, all that's been
                        tested is value 48 mapping to Day-only orders.
                        48 - Day
                        49 - GTC Good till canceled
                        201 - Day + extended hours
            limit_price (number) - The limit price to set with the order, if necessary.
            stop_price (number) -  The stop price to set with the order, if necessary.
            primary_security_type (int) - The type of the security being traded.
            valid_return_codes (set) - Schwab returns an orderReturnCode in the response to both
                        the verification and execution requests, and it appears to be the
                        "severity" for the highest severity message.
                        Verification response messages with severity 10 include:
                            - The market is now closed. This order will be placed for the next
                              trading day
                            - You are purchasing an ETF...please read the prospectus
                            - It is your responsibility to choose the cost basis method
                              appropriate to your tax situation
                            - Quote at the time of order verification: $xx.xx
                        Verification response messages with severity 20 include at least:
                            - Insufficient settled funds (different from insufficient buying power)
                        Verification response messages with severity 25 include at least:
                            - This order is executable because the buy (or sell) limit is higher
                              (lower) than the ask (bid) price.
                        For the execution response, the orderReturnCode is typically 0 for a
                        successfully placed order.
                        Execution response messages with severity 30 include:
                            - Order Affirmation required (This means Schwab wants you to confirm
                              that you really meant to place this order as-is since something about
                              it meets Schwab's criteria for requiring verification. This is
                              usually analogous to a checkbox you would need to check when using
                              the web interface)
            affirm_order (bool) - Schwab requires additional verification for certain orders, such
                        as when a limit order is executable, or when buying some commodity ETFs.
                        Setting this to True will likely provide the verification needed to execute
                        these orders. You will likely also have to include the appropriate return
                        code in valid_return_codes.
            costBasis (str) - Set the cost basis for a sell order. Important tax implications. See:
                         https://help.streetsmart.schwab.com/edge/1.22/Content/Cost%20Basis%20Method.htm
                         Only tested FIFO and BTAX.
                        'FIFO': First In First Out
                        'HCLOT': High Cost
                        'LCLOT': Low Cost
                        'LIFO': Last In First Out
                        'BTAX': Tax Lot Optimizer
                        ('VSP': Specific Lots -> just for reference. Not implemented: Requires to select lots manually.)
            Note: this function calls the new Schwab API, which is flakier and seems to have stricter authentication requirements.
            For now, only use this function if the regular trade function doesn't work for your use case.

            Returns messages (list of strings), is_success (boolean)
        """

        if side == "Buy":
            buySellCode = "49"
        elif side == "Sell":
            buySellCode = "50"
        else:
            raise Exception("side must be either Buy or Sell")

        # Handling formating of limit_price to avoid error.
        # Checking how many decimal places are in limit_price. 
        decimal_places = len(str(float(limit_price)).split('.')[1])
        limit_price_warning = None
        # Max 2 decimal places allowed for price >= $1 and 4 decimal places for price < $1.
        if limit_price >= 1:
            if decimal_places > 2:
                limit_price = round(limit_price,2)
                limit_price_warning = f"For limit_price >= 1, Only 2 decimal places allowed. Rounded price_limit to: {limit_price}"
        else:
            if decimal_places > 4:
                limit_price = round(limit_price,4)
                limit_price_warning = f"For limit_price < 1, Only 4 decimal places allowed. Rounded price_limit to: {limit_price}"

        self.update_token(token_type='update')

        data = {
            "UserContext": {
                "AccountId":str(account_id),
                "AccountColor":0
            },
            "OrderStrategy": {
                # Unclear what the security types map to.
                "PrimarySecurityType":primary_security_type,
                "CostBasisRequest": {
                    "costBasisMethod":costBasis,
                    "defaultCostBasisMethod":costBasis
                },
                "OrderType":str(order_type),
                "LimitPrice":str(limit_price),
                "StopPrice":str(stop_price),
                "Duration":str(duration),
                "AllNoneIn":False,
                "DoNotReduceIn":False,
                "OrderStrategyType":1,
                "OrderLegs":[
                    {
                        "Quantity":str(qty),
                        "LeavesQuantity":str(qty),
                        "Instrument":{"Symbol":ticker},
                        "SecurityType":primary_security_type,
                        "Instruction":buySellCode
                    }
                    ]},
            # OrderProcessingControl seems to map to verification vs actually placing an order.
            "OrderProcessingControl":1
        }

        # Adding this header seems to be necessary.
        self.headers['schwab-resource-version'] = '1.0'

        r = requests.post(urls.order_verification_v2(), json=data, headers=self.headers)
        if r.status_code != 200:
            return [r.text], False

        response = json.loads(r.text)

        orderId = response['orderStrategy']['orderId']
        firstOrderLeg = response['orderStrategy']['orderLegs'][0]
        if "schwabSecurityId" in firstOrderLeg:
            data["OrderStrategy"]["OrderLegs"][0]["Instrument"]["ItemIssueId"] = firstOrderLeg["schwabSecurityId"]

        messages = list()
        if limit_price_warning is not None:
            messages.append(limit_price_warning)
        for message in response["orderStrategy"]["orderMessages"]:
            messages.append(message["message"])

        # TODO: This needs to be fleshed out and clarified.
        if response["orderStrategy"]["orderReturnCode"] not in valid_return_codes:
            return messages, False
        if dry_run:
            return messages, True

        # Make the same POST request, but for real this time.
        data["UserContext"]["CustomerId"] = 0
        data["OrderStrategy"]["OrderId"] = int(orderId)
        data["OrderProcessingControl"] = 2
        if affirm_order:
            data["OrderStrategy"]["OrderAffrmIn"] = True
        self.update_token(token_type='update')
        r = requests.post(urls.order_verification_v2(), json=data, headers=self.headers)

        if r.status_code != 200:
            return [r.text], False

        response = json.loads(r.text)

        messages = list()
        if limit_price_warning is not None:
            messages.append(limit_price_warning)
        if "orderMessages" in response["orderStrategy"] and response["orderStrategy"]["orderMessages"] is not None:
            for message in response["orderStrategy"]["orderMessages"]:
                messages.append(message["message"])

        if response["orderStrategy"]["orderReturnCode"] in valid_return_codes:
            return messages, True

        return messages, False

    def trade_v2_2(self,
        ticker,
        side,
        qty,
        account_id,
        dry_run=True,
        # The Fields below are experimental fields that should only be changed if you know what you're doing.
        order_type=49,
        duration=48,
        limit_price=0,
        stop_price=0,
        primary_security_type=46,
        valid_return_codes = {0,10},
        affirm_order=False,
        # costBasis='FIFO'
        ):
        """
            ticker (Str) - The symbol you want to trade,
            side (str) - Either 'Buy' or 'Sell',
            qty (int) - The amount of shares to buy/sell,
            account_id (int) - The account ID to place the trade on. If the ID is XXXX-XXXX,
                        we're looking for just XXXXXXXX.
            order_type (int) - The order type. This is a Schwab-specific number, and there exists types
                        beyond 49 (Market) and 50 (Limit). This parameter allows setting specific types
                        for those willing to trial-and-error. For reference but not tested: 
                        49 - Market
                        50 - Limit
                        51 - Stop market
                        52 - Stop limit
                        84 - Trailing stop
                        53 - Market on close
            duration (int) - The duration type for the order. For now, all that's been
                        tested is value 48 mapping to Day-only orders.
                        48 - Day
                        49 - GTC Good till canceled
                        201 - Day + extended hours
            limit_price (number) - The limit price to set with the order, if necessary.
            stop_price (number) -  The stop price to set with the order, if necessary.
            primary_security_type (int) - The type of the security being traded.
            valid_return_codes (set) - Schwab returns an orderReturnCode in the response to both
                        the verification and execution requests, and it appears to be the
                        "severity" for the highest severity message.
                        Verification response messages with severity 10 include:
                            - The market is now closed. This order will be placed for the next
                              trading day
                            - You are purchasing an ETF...please read the prospectus
                            - It is your responsibility to choose the cost basis method
                              appropriate to your tax situation
                            - Quote at the time of order verification: $xx.xx
                        Verification response messages with severity 20 include at least:
                            - Insufficient settled funds (different from insufficient buying power)
                        Verification response messages with severity 25 include at least:
                            - This order is executable because the buy (or sell) limit is higher
                              (lower) than the ask (bid) price.
                        For the execution response, the orderReturnCode is typically 0 for a
                        successfully placed order.
                        Execution response messages with severity 30 include:
                            - Order Affirmation required (This means Schwab wants you to confirm
                              that you really meant to place this order as-is since something about
                              it meets Schwab's criteria for requiring verification. This is
                              usually analogous to a checkbox you would need to check when using
                              the web interface)
            affirm_order (bool) - Schwab requires additional verification for certain orders, such
                        as when a limit order is executable, or when buying some commodity ETFs.
                        Setting this to True will likely provide the verification needed to execute
                        these orders. You will likely also have to include the appropriate return
                        code in valid_return_codes.

            costBasis (str) - Set the cost basis for a sell order. Important tax implications. See:
                    https://help.streetsmart.schwab.com/edge/1.22/Content/Cost%20Basis%20Method.htm
                    Only tested FIFO and BTAX.
                    'FIFO': First In First Out
                    'HCLOT': High Cost
                    'LCLOT': Low Cost
                    'LIFO': Last In First Out
                    'BTAX': Tax Lot Optimizer
                    ('VSP': Specific Lots -> just for reference. Not implemented: Requires to select lots manually.)
            Note: this function calls the new Schwab API, which is flakier and seems to have stricter authentication requirements.
            For now, only use this function if the regular trade function doesn't work for your use case.

            Returns messages (list of strings), is_success (boolean)
        """

        if side == "Buy":
            buySellCode = "49"
        elif side == "Sell":
            buySellCode = "50"
        else:
            raise Exception("side must be either Buy or Sell")
        
        # Handling formating of limit_price to avoid error.
        # Checking how many decimal places are in limit_price. 
        decimal_places = len(str(float(limit_price)).split('.')[1])
        limit_price_warning = None
        # Max 2 decimal places allowed for price >= $1 and 4 decimal places for price < $1.
        if limit_price >= 1:
            if decimal_places > 2:
                limit_price = round(limit_price,2)
                limit_price_warning = f"For limit_price >= 1, Only 2 decimal places allowed. Rounded price_limit to: {limit_price}"
        else:
            if decimal_places > 4:
                limit_price = round(limit_price,4)
                limit_price_warning = f"For limit_price < 1, Only 4 decimal places allowed. Rounded price_limit to: {limit_price}"

        self.update_token(token_type='update')

        data = {
            "UserContext": {
                "AccountId":str(account_id),
                "AccountColor":1
            },
            "OrderStrategy": {
                # Unclear what the security types map to.
                "PrimarySecurityType":primary_security_type,
                # "CostBasisRequest": {
                #     "costBasisMethod":costBasis,
                #     "defaultCostBasisMethod":costBasis
                # },
                "OrderType":str(order_type),
                "LimitPrice":str(limit_price),
                "StopPrice":str(stop_price),
                "Duration":str(duration),
                "AllNoneIn":False,
                "DoNotReduceIn":False,
                "MinimumQuantity":0,
                "ReinvestDividend":False,
                "OrderStrategyType":1,
                "OrderLegs":[
                    {
                        "Quantity":str(qty),
                        "LeavesQuantity":str(qty),
                        "Instrument":{"Symbol":ticker},
                        "SecurityType":primary_security_type,
                        "Instruction":buySellCode
                    }
                    ]},
            # OrderProcessingControl seems to map to verification vs actually placing an order.
            "OrderProcessingControl":1
        }
        print("data: ", json.dumps(data))

        # Adding this header seems to be necessary.
        self.headers['schwab-resource-version'] = '1.0'

        r = requests.post(urls.order_verification_v2(), json=data, headers=self.headers)
        if r.status_code != 200:
            return [r.text], False

        response = json.loads(r.text)

        orderId = response['orderStrategy']['orderId']
        firstOrderLeg = response['orderStrategy']['orderLegs'][0]
        if "schwabSecurityId" in firstOrderLeg:
            data["OrderStrategy"]["OrderLegs"][0]["Instrument"]["ItemIssueId"] = firstOrderLeg["schwabSecurityId"]

        messages = list()
        if limit_price_warning is not None:
            messages.append(limit_price_warning)
        for message in response["orderStrategy"]["orderMessages"]:
            messages.append(message["message"])

        # TODO: This needs to be fleshed out and clarified.
        if response["orderStrategy"]["orderReturnCode"] not in valid_return_codes:
            return messages, False

        if dry_run:
            return messages, True

        # Make the same POST request, but for real this time.
        data["UserContext"]["CustomerId"] = 0
        data["OrderStrategy"]["OrderId"] = int(orderId)
        data["OrderProcessingControl"] = 2
        if affirm_order:
            data["OrderStrategy"]["OrderAffrmIn"] = True
        self.update_token(token_type='update')
        r = requests.post(urls.order_verification_v2(), json=data, headers=self.headers)

        if r.status_code != 200:
            return [r.text], False

        response = json.loads(r.text)
        print("response: ", response)

        messages = list()
        if limit_price_warning is not None:
            messages.append(limit_price_warning)
        if "orderMessages" in response["orderStrategy"] and response["orderStrategy"]["orderMessages"] is not None:
            for message in response["orderStrategy"]["orderMessages"]:
                messages.append(message["message"])

        if response["orderStrategy"]["orderReturnCode"] in valid_return_codes:
            return messages, True

        return messages, False
    
    def trade_v2_buy_then_sell_strat(
        self,
        ticker,
        qty,
        account_id,
        limit_buy_price,
        limit_sell_price,
        trailing_stop_dollars=0.07,
        duration=48,
        primary_security_type=46,
        valid_return_codes = {0,10},
        affirm_order=False,
        costBasis='FIFO'
        ):
        """
            buy at limit_buy_price, then trigger OCO with sell limit and trailing stop
        """
        
        # Handling formating of limit_price to avoid error.
        # Checking how many decimal places are in limit prices. 
        decimal_places = len(str(float(limit_buy_price)).split('.')[1])
        limit_price_warning_buy = None
        # Max 2 decimal places allowed for price >= $1 and 4 decimal places for price < $1.
        if limit_buy_price >= 1:
            if decimal_places > 2:
                limit_buy_price = round(limit_buy_price,2)
                limit_price_warning_buy = f"For limit_buy_price >= 1, Only 2 decimal places allowed. Rounded price_limit to: {limit_buy_price}"
        else:
            if decimal_places > 4:
                limit_buy_price = round(limit_buy_price,4)
                limit_price_warning_buy = f"For limit_buy_price < 1, Only 4 decimal places allowed. Rounded price_limit to: {limit_buy_price}"
        
        decimal_places = len(str(float(limit_sell_price)).split('.')[1])
        limit_price_warning_sell = None
        # Max 2 decimal places allowed for price >= $1 and 4 decimal places for price < $1.
        if limit_sell_price >= 1:
            if decimal_places > 2:
                limit_sell_price = round(limit_sell_price,2)
                limit_price_warning_sell = f"For limit_sell_price >= 1, Only 2 decimal places allowed. Rounded price_limit to: {limit_sell_price}"
        else:
            if decimal_places > 4:
                limit_sell_price = round(limit_sell_price,4)
                limit_price_warning_sell = f"For limit_sell_price < 1, Only 4 decimal places allowed. Rounded price_limit to: {limit_sell_price}"

        self.update_token(token_type='update')

        data = {
            "UserContext": {
                "AccountId":str(account_id),
                "AccountColor":0
            },
            "OrderStrategy": {
                # Unclear what the security types map to.
                "PrimarySecurityType":primary_security_type,
                "CostBasisRequest": {
                    "costBasisMethod":costBasis,
                    "defaultCostBasisMethod":costBasis
                },
                "OrderType":"50",
                "LimitPrice":str(limit_buy_price),
                "StopPrice":"0",
                "Duration":str(duration),
                "AllNoneIn":False,
                "DoNotReduceIn":False,
                "OrderStrategyType":5,
                "MinimumQuantity":0,
                "GroupOrderId":0,
                "ChildOrders":[
                    {
                        "ChildOrders":[
                            {
                                "AllNoneIn":False,
                                "DoNotReduceIn":False,
                                "Duration":48,
                                "LimitPrice":str(limit_sell_price),
                                "MinimumQuantity":0,
                                "OrderId":0,
                                "OrderLegs":[
                                    {
                                        "Instruction": 50,
                                        "LeavesQuantity": 1,
                                        "Quantity": 1,
                                        "SecurityType": 46,
                                        "Instrument": {"Symbol": ticker}
                                    }
                                ],
                                "OrderStrategyType":1,
                                "OrderType":50,
                                "PrimarySecurityType":46,
                                "StopPrice":0
                            },
                            {
                                "AllNoneIn":False,
                                "CostBasisRequest":{"costBasisMethod": costBasis, "defaultCostBasisMethod": costBasis, "lotDetails": []},
                                "DoNotReduceIn":False,
                                "Duration":48,
                                "LimitPrice":0,
                                "MinimumQuantity":0,
                                "OrderId":0,
                                "OrderLegs":[
                                    {
                                        "Instruction":50,
                                        "Instrument":{"Symbol": ticker, "ItemIssueId": 0},
                                        "LeavesQuantity":1,
                                        "Quantity":1,
                                        "SecurityType":46,
                                    }
                                ],
                                "OrderStrategyType":1,
                                "OrderType":84,
                                "PrimarySecurityType":46,
                                "StopPrice":0,
                                "TrailingStop": {       
                                    "stopPriceLinkType":1,
                                    "stopPriceOffset":trailing_stop_dollars
                                }
                            }
                        ],
                        "OrderStrategyType":4 # OCO bracket
                    }
                ],
                "OrderLegs":[
                    {
                        "Quantity":str(qty),
                        "LeavesQuantity":str(qty),
                        "Instrument":{"Symbol":ticker},
                        "SecurityType":primary_security_type,
                        "Instruction":49 # Buy
                    }
                ]
            },
            # OrderProcessingControl seems to map to verification vs actually placing an order.
            "OrderProcessingControl":1
        }

        # Adding this header seems to be necessary.
        self.headers['schwab-resource-version'] = '1.0'

        r = requests.post(urls.order_verification_v2(), json=data, headers=self.headers)
        if r.status_code != 200:
            return [r.text], False

        response = json.loads(r.text)

        orderId = response['orderStrategy']['orderId']
        firstOrderLeg = response['orderStrategy']['orderLegs'][0]
        if "schwabSecurityId" in firstOrderLeg:
            data["OrderStrategy"]["OrderLegs"][0]["Instrument"]["ItemIssueId"] = firstOrderLeg["schwabSecurityId"]

        
        messages = list()
        if limit_price_warning_buy is not None:
            messages.append(limit_price_warning_buy)
        if limit_price_warning_sell is not None:
            messages.append(limit_price_warning_sell)
        for message in response["orderStrategy"]["orderMessages"]:
            messages.append(message["message"])

        # TODO: This needs to be fleshed out and clarified.
        if response["orderStrategy"]["orderReturnCode"] not in valid_return_codes:
            return messages, False

        # Make the same POST request, but for real this time.
        data["UserContext"]["CustomerId"] = 0
        data["OrderStrategy"]["OrderId"] = int(orderId)
        data["OrderProcessingControl"] = 2
        if affirm_order:
            data["OrderStrategy"]["OrderAffrmIn"] = True
        self.update_token(token_type='update')
        r = requests.post(urls.order_verification_v2(), json=data, headers=self.headers)

        if r.status_code != 200:
            return [r.text], False

        response = json.loads(r.text)

        messages = list()
        if limit_price_warning_buy is not None:
            messages.append(limit_price_warning_buy)
        if limit_price_warning_sell is not None:
            messages.append(limit_price_warning_sell)
        if "orderMessages" in response["orderStrategy"] and response["orderStrategy"]["orderMessages"] is not None:
            for message in response["orderStrategy"]["orderMessages"]:
                messages.append(message["message"])

        if response["orderStrategy"]["orderReturnCode"] in valid_return_codes:
            return messages, True

        return messages, False
    
    def trade_v2_limit_buy_order(
        self,
        ticker,
        qty,
        account_id,
        limit_price,
        old_order_id = None,
        old_price = None,
        duration=48,
        primary_security_type=46,
        valid_return_codes = {0,10},
        affirm_order=False,
        costBasis='FIFO',
        usingTokenAutoUpdate = False
        ):
        """
            buy at limit_buy_price
        """

        if old_order_id != None and old_price != None:
            messages, success = self.cancel_limit_order_v2(
                account_id=account_id,
                order_id=old_order_id,
                qty=qty,
                buysell="Buy",
                price=old_price,
                ticker=ticker
            )

            if not success:
                print("cancel order in trade_v2_limit_buy_order unsuccessful. leaving function. messages: ", messages)
                return ["same message as above..", ], False, None
        
        # Handling formating of limit_price to avoid error.
        # Checking how many decimal places are in limit prices. 
        decimal_places = len(str(float(limit_price)).split('.')[1])
        limit_price_warning_buy = None
        # Max 2 decimal places allowed for price >= $1 and 4 decimal places for price < $1.
        if limit_price >= 1:
            if decimal_places > 2:
                limit_price = round(limit_price,2)
                limit_price_warning_buy = f"For limit_buy_price >= 1, Only 2 decimal places allowed. Rounded price_limit to: {limit_price}"
        else:
            if decimal_places > 4:
                limit_price = round(limit_price,4)
                limit_price_warning_buy = f"For limit_buy_price < 1, Only 4 decimal places allowed. Rounded price_limit to: {limit_price}"
        if not usingTokenAutoUpdate:
            self.update_token(token_type='update')
        else:
            self.setHeaderToken(self.updateToken)

        data = {
            "UserContext": {
                "AccountId":str(account_id),
                "AccountColor":0
            },
            "OrderStrategy": {
                # Unclear what the security types map to.
                "PrimarySecurityType":primary_security_type,
                "CostBasisRequest": {
                    "costBasisMethod":costBasis,
                    "defaultCostBasisMethod":costBasis
                },
                "OrderType":"50", # Limit
                "LimitPrice":str(limit_price),
                "StopPrice":"0",
                "Duration":str(duration),
                "AllNoneIn":False,
                "DoNotReduceIn":False,
                # "OrderId":old_order_id,
                # "OrderSystem":"1" if old_order_id else None,
                "OrderStrategyType":1,
                "MinimumQuantity":0,
                "OrderLegs":[
                    {
                        "Quantity":str(qty),
                        "LeavesQuantity":str(qty),
                        "Instrument":{"Symbol":ticker},
                        "SecurityType":primary_security_type,
                        "Instruction":49 # Buy
                    }
                ]
            },
            # OrderProcessingControl seems to map to verification vs actually placing an order.
            "OrderProcessingControl":1
        }

        # Adding this header seems to be necessary.
        
        headers = dict(self.headers)
        headers['schwab-resource-version'] = '1.0'
        r = requests.post(urls.order_verification_v2(), json=data, headers=headers, timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            print("bad status code. response: ", r.headers, ", ", r.content,  ", r status code: ", r.status_code)
            return [r.text], False, None

        response = json.loads(r.text)

        orderId = response['orderStrategy']['orderId']
        firstOrderLeg = response['orderStrategy']['orderLegs'][0]
        if "schwabSecurityId" in firstOrderLeg:
            data["OrderStrategy"]["OrderLegs"][0]["Instrument"]["ItemIssueId"] = firstOrderLeg["schwabSecurityId"]

        
        messages = list()
        if limit_price_warning_buy is not None:
            messages.append(limit_price_warning_buy)
        for message in response["orderStrategy"]["orderMessages"]:
            messages.append(message["message"])

        # TODO: This needs to be fleshed out and clarified.
        if response["orderStrategy"]["orderReturnCode"] not in valid_return_codes:
            print("invalid return code: ", response["orderStrategy"]["orderReturnCode"])
            return messages, False, None

        # Make the same POST request, but for real this time.
        data["UserContext"]["CustomerId"] = 0
        data["OrderStrategy"]["OrderId"] = int(orderId)
        data["OrderProcessingControl"] = 2
        if affirm_order:
            data["OrderStrategy"]["OrderAffrmIn"] = True
        if not usingTokenAutoUpdate:
            self.update_token(token_type='update')
        # if old_order_id != None:
        #     data["OrderStrategy"]["CancelOrderId"] = old_order_id
        #     data["OrderStrategy"]["OrderId"] = old_order_id
        headers = dict(self.headers)
        headers['schwab-resource-version'] = '1.0'
        r = requests.post(urls.order_verification_v2(), json=data, headers=headers, timeout=REQUEST_TIMEOUT)

        if r.status_code != 200:
            print("limit buy status code wrong. r.text: ", r.text)
            return [r.text], False, None

        response = json.loads(r.text)

        messages = list()
        if limit_price_warning_buy is not None:
            messages.append(limit_price_warning_buy)
        if "orderMessages" in response["orderStrategy"] and response["orderStrategy"]["orderMessages"] is not None:
            for message in response["orderStrategy"]["orderMessages"]:
                messages.append(message["message"])

        if response["orderStrategy"]["orderReturnCode"] in valid_return_codes:
            return messages, True, response['orderStrategy']['orderId']

        print("returning with no valid return codes at end: ", response["orderStrategy"]["orderReturnCode"])
        return messages, False, None
    
    def trade_v2_limit_sell_order(
        self,
        ticker,
        qty,
        account_id,
        limit_price,
        old_order_id = None,
        old_price = None,
        duration=48,
        primary_security_type=46,
        valid_return_codes = {0,10},
        affirm_order=False,
        costBasis='FIFO',
        usingTokenAutoUpdate = False
        ):
        """
            sell at limit_price
        """

        if old_order_id != None:
            messages, success = self.cancel_limit_order_v2(
                account_id=account_id,
                order_id=old_order_id,
                qty=qty,
                buysell="Sell",
                price=old_price,
                ticker=ticker,
                usingTokenAutoUpdate=usingTokenAutoUpdate
            )

            if not success:
                print("cancel order in trade_v2_limit_sell_order unsuccessful. leaving function. messages: ", messages)
                return ["same message as above..", ], False, None
        
        # Handling formating of limit_price to avoid error.
        # Checking how many decimal places are in limit prices. 
        decimal_places = len(str(float(limit_price)).split('.')[1])
        limit_price_warning = None
        # Max 2 decimal places allowed for price >= $1 and 4 decimal places for price < $1.
        if limit_price >= 1:
            if decimal_places > 2:
                limit_price = round(limit_price,2)
                limit_price_warning = f"For limit_price >= 1, Only 2 decimal places allowed. Rounded price_limit to: {limit_price}"
        else:
            if decimal_places > 4:
                limit_price = round(limit_price,4)
                limit_price_warning = f"For limit_price < 1, Only 4 decimal places allowed. Rounded price_limit to: {limit_price}"

        if not usingTokenAutoUpdate:
            self.update_token(token_type='update')
        else:
            self.setHeaderToken(self.updateToken)

        data = {
            "UserContext": {
                "AccountId":str(account_id),
                "AccountColor":0
            },
            "OrderStrategy": {
                # Unclear what the security types map to.
                "PrimarySecurityType":primary_security_type,
                "CostBasisRequest": {
                    "costBasisMethod":costBasis,
                    "defaultCostBasisMethod":costBasis
                },
                "OrderType":"50", # Limit
                "LimitPrice":str(limit_price),
                "StopPrice":"0",
                "Duration":str(duration),
                "AllNoneIn":False,
                "DoNotReduceIn":False,
                "OrderStrategyType":1,
                "MinimumQuantity":0,
                "OrderLegs":[
                    {
                        "Quantity":str(qty),
                        "LeavesQuantity":str(qty),
                        "Instrument":{"Symbol":ticker},
                        "SecurityType":primary_security_type,
                        "Instruction":50 # Sell
                    }
                ]
            },
            # OrderProcessingControl seems to map to verification vs actually placing an order.
            "OrderProcessingControl":1
        }

        # Adding this header seems to be necessary.
        
        headers = dict(self.headers)
        headers['schwab-resource-version'] = '1.0'
        r = requests.post(urls.order_verification_v2(), json=data, headers=headers, timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            print("bad status code. response: ", r.headers, ", ", r.content,  ", r status code: ", r.status_code)
            return [r.text], False, None

        response = json.loads(r.text)

        orderId = response['orderStrategy']['orderId']
        firstOrderLeg = response['orderStrategy']['orderLegs'][0]
        if "schwabSecurityId" in firstOrderLeg:
            data["OrderStrategy"]["OrderLegs"][0]["Instrument"]["ItemIssueId"] = firstOrderLeg["schwabSecurityId"]

        
        messages = list()
        if limit_price_warning is not None:
            messages.append(limit_price_warning)
        for message in response["orderStrategy"]["orderMessages"]:
            messages.append(message["message"])

        # TODO: This needs to be fleshed out and clarified.
        if response["orderStrategy"]["orderReturnCode"] not in valid_return_codes:
            print("invalid return code: ", response["orderStrategy"]["orderReturnCode"])
            return messages, False, None

        # Make the same POST request, but for real this time.
        data["UserContext"]["CustomerId"] = 0
        data["OrderStrategy"]["OrderId"] = int(orderId)
        data["OrderProcessingControl"] = 2
        if affirm_order:
            data["OrderStrategy"]["OrderAffrmIn"] = True
        if not usingTokenAutoUpdate:
            self.update_token(token_type='update')
        
        headers = dict(self.headers)
        headers['schwab-resource-version'] = '1.0'
        r = requests.post(urls.order_verification_v2(), json=data, headers=headers, timeout=REQUEST_TIMEOUT)

        if r.status_code != 200:
            print("limit sell status code wrong. r.text: ", r.text)
            return [r.text], False, None

        response = json.loads(r.text)

        messages = list()
        if limit_price_warning is not None:
            messages.append(limit_price_warning)
        if "orderMessages" in response["orderStrategy"] and response["orderStrategy"]["orderMessages"] is not None:
            for message in response["orderStrategy"]["orderMessages"]:
                messages.append(message["message"])

        if response["orderStrategy"]["orderReturnCode"] in valid_return_codes:
            return messages, True, response['orderStrategy']['orderId']

        return messages, False, None
    
    def trade_v2_buy_OCO_ONLY(
        self,
        ticker,
        qty,
        account_id,
        limit_price,
        trailing_stop_dollars=0.07,
        duration=48,
        primary_security_type=46,
        valid_return_codes = {0,10, 20},
        affirm_order=False,
        costBasis='FIFO'
        ):
        """
            trigger OCO with buy limit and trailing stop
        """
        
        # Handling formating of limit_price to avoid error.
        # Checking how many decimal places are in limit prices.
        
        decimal_places = len(str(float(limit_price)).split('.')[1])
        limit_price_warning = None
        # Max 2 decimal places allowed for price >= $1 and 4 decimal places for price < $1.
        if limit_price >= 1:
            if decimal_places > 2:
                limit_price = round(limit_price,2)
                limit_price_warning = f"For limit_buy_price >= 1, Only 2 decimal places allowed. Rounded price_limit to: {limit_price}"
        else:
            if decimal_places > 4:
                limit_price = round(limit_price,4)
                limit_price_warning = f"For limit_buy_price < 1, Only 4 decimal places allowed. Rounded price_limit to: {limit_price}"

        self.update_token(token_type='update')

        data = {
            "UserContext": {
                "AccountId":str(account_id),
                "AccountColor":1,
                "CustomerId": 0
            },
            "OrderStrategy": {
                "OrderStrategyType":4, # OCO bracket
                "GroupOrderId":0,
                "ChildOrders":[
                    {
                        "AllNoneIn":False,
                        "DoNotReduceIn":False,
                        "Duration":str(duration),
                        "LimitPrice":str(limit_price),
                        "MinimumQuantity":0,
                        "OrderId":0,
                        "OrderLegs":[
                            {
                                "Instruction": 49,
                                "LeavesQuantity": str(qty),
                                "Quantity": str(qty),
                                "SecurityType": 46,
                                "Instrument": {"Symbol": ticker}
                            }
                        ],
                        "OrderStrategyType":1,
                        "OrderType":"50",
                        "PrimarySecurityType":46,
                        "StopPrice":"0"
                    },
                    {
                        "AllNoneIn":False,
                        "DoNotReduceIn":False,
                        "Duration":duration,
                        "LimitPrice":0,
                        "MinimumQuantity":0,
                        "OrderId":0,
                        "OrderLegs":[
                            {
                                "Instruction":49,
                                "Instrument":{"Symbol": ticker},
                                "LeavesQuantity":str(qty),
                                "Quantity":str(qty),
                                "SecurityType":46,
                            }
                        ],
                        "OrderStrategyType":1,
                        "OrderType":84,
                        "PrimarySecurityType":46,
                        "ReinvestDividend": False,
                        "StopPrice":"0",
                        "TrailingStop": {       
                            "stopPriceLinkType":1,
                            "stopPriceOffset":trailing_stop_dollars
                        }
                    }
                ],
                "OrderLegs":[
                    {
                        "Quantity":str(qty),
                        "LeavesQuantity":str(qty),
                        "Instrument":{"Symbol":ticker},
                        "SecurityType":primary_security_type,
                        "Instruction":49 # Buy
                    }
                ]
            },
            # OrderProcessingControl seems to map to verification vs actually placing an order.
            "OrderProcessingControl":1
        }

        # Adding this header seems to be necessary.
        self.headers['schwab-resource-version'] = '1.0'

        r = requests.post(urls.order_verification_v2(), json=data, headers=self.headers)
        if r.status_code != 200:
            return [r.text], False

        response = json.loads(r.text)

        orderId = response['orderStrategy']['orderId']
        firstOrderLeg = response['orderStrategy']['orderLegs'][0]
        if "schwabSecurityId" in firstOrderLeg:
            data["OrderStrategy"]["OrderLegs"][0]["Instrument"]["ItemIssueId"] = firstOrderLeg["schwabSecurityId"]

        
        messages = list()
        if limit_price_warning is not None:
            messages.append(limit_price_warning)
        for message in response["orderStrategy"]["orderMessages"]:
            messages.append(message["message"])

        # TODO: This needs to be fleshed out and clarified.
        if response["orderStrategy"]["orderReturnCode"] not in valid_return_codes:
            return messages, False

        # Make the same POST request, but for real this time.
        data["UserContext"]["CustomerId"] = 0
        data["OrderStrategy"]["OrderId"] = orderId
        data["OrderProcessingControl"] = 2
        if affirm_order:
            data["OrderStrategy"]["OrderAffrmIn"] = True
        self.update_token(token_type='update')
        self.headers['schwab-resource-version'] = '1.0'
        r = requests.post(urls.order_verification_v2(), json=data, headers=self.headers)

        if r.status_code != 200:
            return [r.text], False

        response = json.loads(r.text)

        messages = list()
        if limit_price_warning is not None:
            messages.append(limit_price_warning)
        if "orderMessages" in response["orderStrategy"] and response["orderStrategy"]["orderMessages"] is not None:
            for message in response["orderStrategy"]["orderMessages"]:
                messages.append(message["message"])

        if response["orderStrategy"]["orderReturnCode"] in valid_return_codes:
            return messages, True

        return messages, False
    
    def trade_v2_sell_OCO_ONLY(
        self,
        ticker,
        qty,
        account_id,
        limit_price,
        trailing_stop_dollars=0.07,
        duration=48,
        primary_security_type=46,
        valid_return_codes = {0,10,20},
        affirm_order=False,
        costBasis='FIFO'
        ):
        """
            trigger OCO with sell limit and trailing stop
        """
        
        # Handling formating of limit_price to avoid error.
        # Checking how many decimal places are in limit prices.
        
        decimal_places = len(str(float(limit_price)).split('.')[1])
        limit_price_warning = None
        # Max 2 decimal places allowed for price >= $1 and 4 decimal places for price < $1.
        if limit_price >= 1:
            if decimal_places > 2:
                limit_price = round(limit_price,2)
                limit_price_warning = f"For limit_price >= 1, Only 2 decimal places allowed. Rounded price_limit to: {limit_price}"
        else:
            if decimal_places > 4:
                limit_price = round(limit_price,4)
                limit_price_warning = f"For limit_price < 1, Only 4 decimal places allowed. Rounded price_limit to: {limit_price}"

        self.update_token(token_type='update')

        data = {
            "UserContext": {
                "AccountId":str(account_id),
                "AccountColor":1,
                "CustomerId": 0
            },
            "OrderStrategy": {
                "OrderStrategyType":4, # OCO bracket
                "GroupOrderId":0,
                "ChildOrders":[
                    {
                        "AllNoneIn":False,
                        "DoNotReduceIn":False,
                        "Duration":str(duration),
                        "LimitPrice":str(limit_price),
                        "MinimumQuantity":0,
                        "OrderId":0,
                        "OrderLegs":[
                            {
                                "Instruction": 50, # sell (short sell = 53)
                                "LeavesQuantity": str(qty),
                                "Quantity": str(qty),
                                "SecurityType": 46,
                                "Instrument": {"Symbol": ticker}
                            }
                        ],
                        "OrderStrategyType":1,
                        "OrderType":"50",
                        "PrimarySecurityType":46,
                        "StopPrice":"0"
                    },
                    {
                        "AllNoneIn":False,
                        "DoNotReduceIn":False,
                        "Duration":duration,
                        "LimitPrice":0,
                        "MinimumQuantity":0,
                        "OrderId":0,
                        "OrderLegs":[
                            {
                                "Instruction":50, # sell (short sell = 53)
                                "Instrument":{"Symbol": ticker},
                                "LeavesQuantity":str(qty),
                                "Quantity":str(qty),
                                "SecurityType":46,
                            }
                        ],
                        "OrderStrategyType":1,
                        "OrderType":84,
                        "PrimarySecurityType":46,
                        "ReinvestDividend": False,
                        "StopPrice":"0",
                        "TrailingStop": {       
                            "stopPriceLinkType":1,
                            "stopPriceOffset":trailing_stop_dollars
                        }
                    }
                ],
                "OrderLegs":[
                    {
                        "Quantity":str(qty),
                        "LeavesQuantity":str(qty),
                        "Instrument":{"Symbol":ticker},
                        "SecurityType":primary_security_type,
                        "Instruction":50 # sell (short sell = 53)
                    }
                ]
            },
            # OrderProcessingControl seems to map to verification vs actually placing an order.
            "OrderProcessingControl":1
        }

        # Adding this header seems to be necessary.
        self.headers['schwab-resource-version'] = '1.0'

        r = requests.post(urls.order_verification_v2(), json=data, headers=self.headers)
        if r.status_code != 200:
            return [r.text], False

        response = json.loads(r.text)

        orderId = response['orderStrategy']['orderId']
        firstOrderLeg = response['orderStrategy']['orderLegs'][0]
        if "schwabSecurityId" in firstOrderLeg:
            data["OrderStrategy"]["OrderLegs"][0]["Instrument"]["ItemIssueId"] = firstOrderLeg["schwabSecurityId"]

        
        messages = list()
        if limit_price_warning is not None:
            messages.append(limit_price_warning)
        for message in response["orderStrategy"]["orderMessages"]:
            messages.append(message["message"])

        # TODO: This needs to be fleshed out and clarified.
        if response["orderStrategy"]["orderReturnCode"] not in valid_return_codes:
            return messages, False

        # Make the same POST request, but for real this time.
        data["UserContext"]["CustomerId"] = 0
        data["OrderStrategy"]["OrderId"] = orderId
        data["OrderProcessingControl"] = 2
        if affirm_order:
            data["OrderStrategy"]["OrderAffrmIn"] = True
        self.update_token(token_type='update')
        self.headers['schwab-resource-version'] = '1.0'
        r = requests.post(urls.order_verification_v2(), json=data, headers=self.headers)

        if r.status_code != 200:
            return [r.text], False

        response = json.loads(r.text)

        messages = list()
        if limit_price_warning is not None:
            messages.append(limit_price_warning)
        if "orderMessages" in response["orderStrategy"] and response["orderStrategy"]["orderMessages"] is not None:
            for message in response["orderStrategy"]["orderMessages"]:
                messages.append(message["message"])

        if response["orderStrategy"]["orderReturnCode"] in valid_return_codes:
            return messages, True

        return messages, False

    def trade_v2_sell_OCO_ONLY_OLD(
        self,
        ticker,
        qty,
        account_id,
        limit_price,
        trailing_stop_dollars=0.07,
        duration=48,
        primary_security_type=46,
        valid_return_codes = {0,10},
        affirm_order=False,
        costBasis='FIFO'
        ):
        """
            trigger OCO with sell limit and trailing stop
        """
        
        # Handling formating of limit_price to avoid error.
        # Checking how many decimal places are in limit prices.
        
        decimal_places = len(str(float(limit_price)).split('.')[1])
        limit_price_warning_sell = None
        # Max 2 decimal places allowed for price >= $1 and 4 decimal places for price < $1.
        if limit_price >= 1:
            if decimal_places > 2:
                limit_price = round(limit_price,2)
                limit_price_warning_sell = f"For limit_sell_price >= 1, Only 2 decimal places allowed. Rounded price_limit to: {limit_price}"
        else:
            if decimal_places > 4:
                limit_price = round(limit_price,4)
                limit_price_warning_sell = f"For limit_sell_price < 1, Only 4 decimal places allowed. Rounded price_limit to: {limit_price}"

        self.update_token(token_type='update')

        data = {
            "UserContext": {
                "AccountId":str(account_id),
                "AccountColor":1
            },
            "OrderStrategy": {
                "OrderStrategyType":4, # OCO bracket
                "GroupOrderId":0,
                "ChildOrders":[
                    {
                        "AllNoneIn":False,
                        "DoNotReduceIn":False,
                        "Duration":duration,
                        "LimitPrice":str(limit_price),
                        "MinimumQuantity":0,
                        "OrderId":0,
                        "OrderLegs":[
                            {
                                "Instruction": 50, # sell   (short sell is 53)
                                "LeavesQuantity": str(qty),
                                "Quantity": str(qty),
                                "SecurityType": 46,
                                "Instrument": {"Symbol": ticker}
                            }
                        ],
                        "OrderStrategyType":1,
                        "OrderType":50,
                        "PrimarySecurityType":46,
                        "StopPrice":0
                    },
                    {
                        "AllNoneIn":False,
                        "DoNotReduceIn":False,
                        "Duration":48,
                        "LimitPrice":0,
                        "MinimumQuantity":0,
                        "OrderId":0,
                        "OrderLegs":[
                            {
                                "Instruction":50, # sell
                                "Instrument":{"Symbol": ticker, "ItemIssueId": 0},
                                "LeavesQuantity": str(qty),
                                "Quantity": str(qty),
                                "SecurityType":46,
                            }
                        ],
                        "OrderStrategyType":1,
                        "OrderType":84,
                        "PrimarySecurityType":46,
                        "StopPrice":0,
                        "TrailingStop": {       
                            "stopPriceLinkType":1,
                            "stopPriceOffset":trailing_stop_dollars
                        }
                    }
                ],
                "OrderLegs":[
                    {
                        "Quantity":str(qty),
                        "LeavesQuantity":str(qty),
                        "Instrument":{"Symbol":ticker},
                        "SecurityType":primary_security_type,
                        "Instruction":50 # Buy
                    }
                ]
            },
            # OrderProcessingControl seems to map to verification vs actually placing an order.
            "OrderProcessingControl":1
        }

        # Adding this header seems to be necessary.
        self.headers['schwab-resource-version'] = '1.0'

        r = requests.post(urls.order_verification_v2(), json=data, headers=self.headers)
        if r.status_code != 200:
            return [r.text], False

        response = json.loads(r.text)

        orderId = response['orderStrategy']['orderId']
        firstOrderLeg = response['orderStrategy']['orderLegs'][0]
        if "schwabSecurityId" in firstOrderLeg:
            data["OrderStrategy"]["OrderLegs"][0]["Instrument"]["ItemIssueId"] = firstOrderLeg["schwabSecurityId"]

        
        messages = list()
        if limit_price_warning_sell is not None:
            messages.append(limit_price_warning_sell)
        for message in response["orderStrategy"]["orderMessages"]:
            messages.append(message["message"])

        # TODO: This needs to be fleshed out and clarified.
        if response["orderStrategy"]["orderReturnCode"] not in valid_return_codes:
            return messages, False

        # Make the same POST request, but for real this time.
        data["UserContext"]["CustomerId"] = 0
        data["OrderStrategy"]["OrderId"] = int(orderId)
        data["OrderProcessingControl"] = 2
        if affirm_order:
            data["OrderStrategy"]["OrderAffrmIn"] = True
        self.update_token(token_type='update')
        self.headers['schwab-resource-version'] = '1.0'
        r = requests.post(urls.order_verification_v2(), json=data, headers=self.headers)

        if r.status_code != 200:
            return [r.text], False

        response = json.loads(r.text)

        messages = list()
        if limit_price_warning_sell is not None:
            messages.append(limit_price_warning_sell)
        if "orderMessages" in response["orderStrategy"] and response["orderStrategy"]["orderMessages"] is not None:
            for message in response["orderStrategy"]["orderMessages"]:
                messages.append(message["message"])

        if response["orderStrategy"]["orderReturnCode"] in valid_return_codes:
            return messages, True

        return messages, False

    def cancel_order_v2(
            self, account_id, order_id,
            # The fields below are experimental and should only be changed if you know what
            # you're doing.
            instrument_type=46,
            ):
        """
        Cancels an open order (specified by order ID) using the v2 API

        account_id (int) - The account ID of the order. If the ID is XXXX-XXXX, we're looking for
            just XXXXXXXX.
        order_id (int) - The order ID as listed in orders_v2. The most recent order ID is likely:
            orders_v2(account_id=account_id)[0]['OrderList'][0]['OrderId'].
            Note: the order IDs listed in the v1 orders() are different
        instrument_type (int) - It is unclear what this means or when it should be different
        """
        data = {
            "TypeOfOrder": 0,
            "OrderManagementSystem": 2,
            "Orders": [{
                "OrderId": order_id,
                "IsLiveOrder": True,
                "InstrumentType": instrument_type,
                "CancelOrderLegs": [{}],
                }],
            "ContingentIdToCancel": 0,
            "OrderIdToCancel": 0,
            "OrderProcessingControl": 1,
            "ConfirmCancelOrderId": 0,
            }
        self.headers["schwab-client-account"] = account_id
        self.headers['schwab-resource-version'] = '2.0'
        # Web interface uses bearer token retrieved from:
        # https://client.schwab.com/api/auth/authorize/scope/api
        # and it seems to be good for 1800s (30min)
        self.update_token(token_type='api')
        r1 = requests.post(urls.cancel_order_v2(), json=data, headers=self.headers)
        if r1.status_code not in (200, 202):
            return [r1.text], False

        try:
            response = json.loads(r1.text)
            cancel_order_id = response['CancelOrderId']
        except (json.decoder.JSONDecodeError, KeyError):
            return [r1.text], False

        data['ConfirmCancelOrderId'] = cancel_order_id
        data['OrderProcessingControl'] = 2
        # Web interface uses bearer token retrieved from:
        # https://client.schwab.com/api/auth/authorize/scope/api
        # and it seems to be good for 1800s (30min)
        self.update_token(token_type='api')
        r2 = requests.post(urls.cancel_order_v2(), json=data, headers=self.headers)
        if r2.status_code not in (200, 202):
            return [r2.text], False
        try:
            response = json.loads(r2.text)
            if response["CancelOperationSuccessful"]:
                return response, True
        except (json.decoder.JSONDecodeError, KeyError):
            return [r2.text], False
        return response, False
    
    def cancel_limit_order_v2(
            self, account_id, order_id, ticker, buysell, price, qty,
            # The fields below are experimental and should only be changed if you know what
            # you're doing.
            instrument_type=46,
            usingTokenAutoUpdate=False
            ):
        """
        Cancels an open order (specified by order ID) using the v2 API

        account_id (int) - The account ID of the order. If the ID is XXXX-XXXX, we're looking for
            just XXXXXXXX.
        order_id (int) - The order ID as listed in orders_v2. The most recent order ID is likely:
            orders_v2(account_id=account_id)[0]['OrderList'][0]['OrderId'].
            Note: the order IDs listed in the v1 orders() are different
        instrument_type (int) - It is unclear what this means or when it should be different
        """

        data = {
            "TypeOfOrder": 0,
            "OrderManagementSystem": 1,
            "Orders": [{
                "OrderId": order_id,
                "IsLiveOrder": True,
                "InstrumentType": instrument_type,
                "IsOrphanConditional": False,
                "Price": "Limit $" + str(round(price, 2)),
                "CancelOrderLegs": [
                    {
                        "Action":buysell,
                        "Quantity":str(qty),
                        "QuantityUnitCode":qty,
                        "Symbol":ticker,
                    }
                ],
            }],
            "ContingentIdToCancel": 0,
            "OrderIdToCancel": 0,
            "OrderProcessingControl": 1,
            "ConfirmCancelOrderId": 0,
            }
        self.headers["schwab-client-account"] = account_id
        
        headers = dict(self.headers)
        headers['schwab-resource-version'] = '2.0'
        # Web interface uses bearer token retrieved from:
        # https://client.schwab.com/api/auth/authorize/scope/api
        # and it seems to be good for 1800s (30min)
        if not usingTokenAutoUpdate:
            self.update_token(token_type='api')
        else:
            self.setHeaderToken(self.apiToken)
        r1 = requests.post(urls.cancel_order_v2(), json=data, headers=headers, timeout=REQUEST_TIMEOUT)
        if r1.status_code not in (200, 202):
            return [r1.text], False

        try:
            response = json.loads(r1.text)
            cancel_order_id = response['CancelOrderId']
        except (json.decoder.JSONDecodeError, KeyError):
            print("cancel json decode key error")
            return [r1.text], False

        data['ConfirmCancelOrderId'] = cancel_order_id
        data['OrderProcessingControl'] = 2
        # Web interface uses bearer token retrieved from:
        # https://client.schwab.com/api/auth/authorize/scope/api
        # and it seems to be good for 1800s (30min)
        if not usingTokenAutoUpdate:
            self.update_token(token_type='api')
        r2 = requests.post(urls.cancel_order_v2(), json=data, headers=headers, timeout=REQUEST_TIMEOUT)
        if r2.status_code not in (200, 202):
            print("bad status code, in cancel")
            return [r2.text], False
        try:
            response = json.loads(r2.text)
            if response["CancelOperationSuccessful"]:
                return response, True
        except (json.decoder.JSONDecodeError, KeyError):
            print("cancel json decode key error 2")
            return [r2.text], False
        print("err reached end of cancel")
        return response, False


    def replace_limit_order_v2( # ERR _ NOTE _  NOT WORKING
            self,
            account_id,
            order_id,
            isBuy,
            new_price,
            # The fields below are experimental and should only be changed if you know what
            # you're doing.
            instrument_type=46,
            ):
        """
        Replaces an open order (specified by order ID) using the v2 API

        account_id (int) - The account ID of the order. If the ID is XXXX-XXXX, we're looking for
            just XXXXXXXX.
        order_id (int) - The order ID as listed in orders_v2. The most recent order ID is likely:
            orders_v2(account_id=account_id)[0]['OrderList'][0]['OrderId'].
            Note: the order IDs listed in the v1 orders() are different
        instrument_type (int) - It is unclear what this means or when it should be different
        """
        data = {
            "TypeOfOrder": 0,
            "OrderManagementSystem": 2,
            "Orders": [{
                "OrderId": order_id,
                "IsLiveOrder": True,
                "InstrumentType": instrument_type,
                "CancelOrderLegs": [{}],
                }],
            "ContingentIdToCancel": 0,
            "OrderIdToCancel": 0,
            "OrderProcessingControl": 1,
            "ConfirmCancelOrderId": 0,
            }
        self.headers["schwab-client-account"] = account_id
        self.headers['schwab-resource-version'] = '2.0'
        # Web interface uses bearer token retrieved from:
        # https://client.schwab.com/api/auth/authorize/scope/api
        # and it seems to be good for 1800s (30min)
        self.update_token(token_type='api')
        r1 = requests.post(urls.replace_order_v2(order_id), json=data, headers=self.headers)
        if r1.status_code not in (200, 202):
            return [r1.text], False

        try:
            response = json.loads(r1.text)
            cancel_order_id = response['CancelOrderId']
        except (json.decoder.JSONDecodeError, KeyError):
            return [r1.text], False

        data['ConfirmCancelOrderId'] = cancel_order_id
        data['OrderProcessingControl'] = 2
        # Web interface uses bearer token retrieved from:
        # https://client.schwab.com/api/auth/authorize/scope/api
        # and it seems to be good for 1800s (30min)
        self.update_token(token_type='api')
        r2 = requests.post(urls.replace_order_v2(order_id), json=data, headers=self.headers)
        if r2.status_code not in (200, 202):
            return [r2.text], False
        try:
            response = json.loads(r2.text)
            if response["CancelOperationSuccessful"]:
                return response, True
        except (json.decoder.JSONDecodeError, KeyError):
            return [r2.text], False
        return response, False


    def getBidAsk(self, ticker, account_id, usingTokenAutoUpdate=False):
        try:
            quotes = self.quote_v2([ticker,], account_id, usingTokenAutoUpdate) # assume 'symbol' (in data) is correct - only getting one ticker
            if quotes == None:
                raise Exception("quotes is None in getBidAsk")
            quote = quotes[0]["quote"]
        except Exception as e:
            print("error getting bid/ask. quotes: " + str(quotes) + ", exception: ", e)
        return float(quote["bid"]), float(quote['ask'])


    def quote_v2(self, tickers, account_id, usingTokenAutoUpdate=False):
        """
        quote_v2 takes a list of Tickers, and returns Quote information through the Schwab API.
        """
        data = {
            "Symbols":tickers,
            "IsIra":False,
            "AccountRegType":"S3"
        }

        # Adding this header seems to be necessary.
        self.headers["schwab-client-account"] = account_id
        headers = dict(self.headers)
        headers['schwab-resource-version'] = '1.0'

        if not usingTokenAutoUpdate:
            self.update_token(token_type='update')
        else:
            self.setHeaderToken(self.updateToken)
        r = requests.post(urls.ticker_quotes_v2(), json=data, headers=headers, timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            return [r.text], False

        response = json.loads(r.text)
        return response["quotes"]

    def orders_v2(self, account_id=None, openOnly=False):
        """
        orders_v2 returns a list of orders for a Schwab Account. It is unclear to me how to filter by specific account.

        Currently, the query parameters are hard coded to return ALL orders, but this can be easily adjusted.
        """

        self.update_token(token_type='api')
        self.headers['schwab-resource-version'] = '2.0'
        if account_id:
            self.headers["schwab-client-account"] = account_id
        r = requests.get(urls.orders_v2(), headers=self.headers)
        if r.status_code != 200:
            return [r.text], False

        response = json.loads(r.text)
        return response["Orders"]
    
    def todays_orders_v2(self, account_id=None) -> tuple[list, bool]:
        """
        orders_v2 returns a list of orders for a Schwab Account. It is unclear to me how to filter by specific account.

        Currently, the query parameters are hard coded to return ALL orders, but this can be easily adjusted.
        """

        self.update_token(token_type='api')
        self.headers['schwab-resource-version'] = '2.0'
        if account_id:
            self.headers["schwab-client-account"] = account_id
        r = requests.get(urls.todays_orders_v2(), headers=self.headers, timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            return [r.text], False

        response = json.loads(r.text)
        return response["Orders"], True

    def get_account_info_v2(self):
        account_info = dict()
        self.update_token(token_type='api')
        r = requests.get(urls.positions_v2(), headers=self.headers)
        response = json.loads(r.text)
        for account in response['accounts']:
            positions = list()
            for security_group in account["groupedPositions"]:
                if security_group["groupName"] == "Cash":
                    continue
                for position in security_group["positions"]:
                    positions.append(
                        Position(
                            position["symbolDetail"]["symbol"],
                            position["symbolDetail"]["description"],
                            float(position["quantity"]),
                            0 if "costDetail" not in position else float(position["costDetail"]["costBasisDetail"]["costBasis"]),
                            0 if "priceDetail" not in position else float(position["priceDetail"]["marketValue"])
                        )._as_dict()
                    )
            account_info[int(account["accountId"])] = Account(
                account["accountId"],
                positions,
                account["totals"]["marketValue"],
                account["totals"]["cashInvestments"],
                account["totals"]["accountValue"],
                account["totals"].get("costBasis", 0)
            )._as_dict()

        return account_info

    def update_token(self, token_type='api'):
        r = self.session.get(f"https://client.schwab.com/api/auth/authorize/scope/{token_type}")
        if not r.ok:
            raise ValueError(f'Error updating Bearer token: {r.reason} at time {datetime.datetime.now().strftime("%I:%M:%S%p on %D")}')
        token = json.loads(r.text)['token']
        self.setHeaderToken(token)
        return token
    
    def update_both_tokens(self):
        self.updateToken = self.update_token(token_type='update')
        self.apiToken = self.update_token(token_type='api')
        return self.apiToken, self.updateToken
    
    def setHeaderToken(self, token):
        self.headers['authorization'] = f"Bearer {token}"











































    def testBuyOCOthing(
        self,
        ticker,
        qty,
        account_id,
        limit_price,
        trailing_stop_dollars=0.07,
        duration=48,
        primary_security_type=46,
        valid_return_codes = {0,10, 20},
        affirm_order=False,
        costBasis='FIFO',
        newnum = 84
        ):
        """
            trigger OCO with buy limit and trailing stop
        """
        
        # Handling formating of limit_price to avoid error.
        # Checking how many decimal places are in limit prices.
        
        decimal_places = len(str(float(limit_price)).split('.')[1])
        limit_price_warning = None
        # Max 2 decimal places allowed for price >= $1 and 4 decimal places for price < $1.
        if limit_price >= 1:
            if decimal_places > 2:
                limit_price = round(limit_price,2)
                limit_price_warning = f"For limit_buy_price >= 1, Only 2 decimal places allowed. Rounded price_limit to: {limit_price}"
        else:
            if decimal_places > 4:
                limit_price = round(limit_price,4)
                limit_price_warning = f"For limit_buy_price < 1, Only 4 decimal places allowed. Rounded price_limit to: {limit_price}"

        self.update_token(token_type='update')

        data = {
            "UserContext": {
                "AccountId":str(account_id),
                "AccountColor":1,
                "CustomerId": 0
            },
            "OrderStrategy": {
                "OrderStrategyType":4, # OCO bracket
                "GroupOrderId":0,
                "ChildOrders":[
                    {
                        "AllNoneIn":False,
                        "DoNotReduceIn":False,
                        "Duration":str(duration),
                        "LimitPrice":str(limit_price),
                        "MinimumQuantity":0,
                        "OrderId":0,
                        "OrderLegs":[
                            {
                                "Instruction": 49,
                                "LeavesQuantity": str(qty),
                                "Quantity": str(qty),
                                "SecurityType": 46,
                                "Instrument": {"Symbol": ticker}
                            }
                        ],
                        "OrderStrategyType":1,
                        "OrderType":"50",
                        "PrimarySecurityType":46,
                        "StopPrice":"0"
                    },
                    {
                        "AllNoneIn":False,
                        "DoNotReduceIn":False,
                        "Duration":duration,
                        "LimitPrice":0,
                        "MinimumQuantity":0,
                        "OrderId":0,
                        "OrderLegs":[
                            {
                                "Instruction":49,
                                "Instrument":{"Symbol": ticker},
                                "LeavesQuantity":str(qty),
                                "Quantity":str(qty),
                                "SecurityType":46,
                            }
                        ],
                        "OrderStrategyType":1,
                        "OrderType":newnum,
                        "PrimarySecurityType":46,
                        "ReinvestDividend": False,
                        "StopPrice":"0",
                        "TrailingStop": {       
                            "stopPriceLinkType":1,
                            "stopPriceOffset":trailing_stop_dollars
                        }
                    }
                ],
                "OrderLegs":[
                    {
                        "Quantity":str(qty),
                        "LeavesQuantity":str(qty),
                        "Instrument":{"Symbol":ticker},
                        "SecurityType":primary_security_type,
                        "Instruction":49 # Buy
                    }
                ]
            },
            # OrderProcessingControl seems to map to verification vs actually placing an order.
            "OrderProcessingControl":1
        }

        # Adding this header seems to be necessary.
        self.headers['schwab-resource-version'] = '1.0'

        r = requests.post(urls.order_verification_v2(), json=data, headers=self.headers)
        if r.status_code != 200:
            return [r.text], False

        response = json.loads(r.text)

        orderId = response['orderStrategy']['orderId']
        firstOrderLeg = response['orderStrategy']['orderLegs'][0]
        if "schwabSecurityId" in firstOrderLeg:
            data["OrderStrategy"]["OrderLegs"][0]["Instrument"]["ItemIssueId"] = firstOrderLeg["schwabSecurityId"]

        
        messages = list()
        if limit_price_warning is not None:
            messages.append(limit_price_warning)
        for message in response["orderStrategy"]["orderMessages"]:
            messages.append(message["message"])

        # TODO: This needs to be fleshed out and clarified.
        if response["orderStrategy"]["orderReturnCode"] not in valid_return_codes:
            return messages, False

        # Make the same POST request, but for real this time.
        data["UserContext"]["CustomerId"] = 0
        data["OrderStrategy"]["OrderId"] = orderId
        data["OrderProcessingControl"] = 2
        if affirm_order:
            data["OrderStrategy"]["OrderAffrmIn"] = True
        self.update_token(token_type='update')
        self.headers['schwab-resource-version'] = '1.0'
        r = requests.post(urls.order_verification_v2(), json=data, headers=self.headers)

        if r.status_code != 200:
            return [r.text], False

        response = json.loads(r.text)

        messages = list()
        if limit_price_warning is not None:
            messages.append(limit_price_warning)
        if "orderMessages" in response["orderStrategy"] and response["orderStrategy"]["orderMessages"] is not None:
            for message in response["orderStrategy"]["orderMessages"]:
                messages.append(message["message"])

        if response["orderStrategy"]["orderReturnCode"] in valid_return_codes:
            return messages, True

        return messages, False
