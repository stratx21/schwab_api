    def trade_v2_limit_order(
        self,
        ticker,
        qty,
        account_id,
        limit_buy_price,
        old_order_id = None,
        old_price = None,
        duration=48,
        primary_security_type=46,
        valid_return_codes = {0,10},
        affirm_order=False,
        costBasis='FIFO'
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
                print("cancel order in trade_v2_limit_order unsuccessful. leaving function. messages: ", messages)
                return ["same message as above..", ], False, None
        
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
                "OrderType":"50", # Limit
                "LimitPrice":str(limit_buy_price),
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
        self.headers['schwab-resource-version'] = '1.0'

        r = requests.post(urls.order_verification_v2(), json=data, headers=self.headers)
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
        self.update_token(token_type='update')
        # if old_order_id != None:
        #     data["OrderStrategy"]["CancelOrderId"] = old_order_id
        #     data["OrderStrategy"]["OrderId"] = old_order_id
        
        r = requests.post(urls.order_verification_v2(), json=data, headers=self.headers)

        if r.status_code != 200:
            print("status code wrong. r.text: ", r.text)
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