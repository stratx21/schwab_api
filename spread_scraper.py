from schwab_api import Schwab
import json
from queue import Queue
from discord_terminal.discord_terminal import runDiscordTerminalProcess
from strategy.subprocess_management import SchwabManager
from tools.terminal_colors import TermColor
from tools.day_analysis import printDayAnalysis
import multiprocessing



SECONDS_THREAD_SLEEP = 0.1



CONFIG_JSON_FILE_NAME = "config.json"


if __name__ == '__main__':
    # read config file
    username = None
    account_id = None
    with open(CONFIG_JSON_FILE_NAME) as configFile:
        data = json.load(configFile)
        if "schwab" in data.keys():
            schwabConfig = data["schwab"]
            if "username" in schwabConfig.keys():
                username = schwabConfig["username"]
            if "account_id" in schwabConfig.keys():
                account_id = schwabConfig["account_id"]

    if account_id == None:
        print(TermColor.makeWarning("Account id not provided. Please set it in config.json."))
        exit(1)

    # Initialize our schwab instance
    api = Schwab()

    # Login using playwright
    print("Logging into Schwab")
    logged_in = api.login(
        username=username,
        #password=password,
        #totp_secret=totp_secret # Get this by generating TOTP at https://itsjafer.com/#/schwab
    )
    
    api.update_both_tokens()

    
    runDiscordTerminalProcess(CONFIG_JSON_FILE_NAME, account_id, api)
    # discord process 
    # pipeToDiscord, child_connection = multiprocessing.Pipe()
    # discordSubprocess = multiprocessing.Process(
    #     target=runDiscordTerminalProcess,
    #     args=[
    #         CONFIG_JSON_FILE_NAME,
    #         child_connection,
    #         subProcessManager.queue
    #     ]
    # )
    # discordSubprocess.start()

    # pipeToDiscord.send({
    #     "just for fun key": {
    #         "hehe": 33,
    #         "haha": "hooheoh"
    #     }
    # })

    # inputText = None
    # while inputText != 'x':
    #     input("input x to exit: ")
    # pipeToDiscord.send({
    #     "stopProcess": 0,
    # })
    # discordSubprocess.join()
    # exit(0)


    # inputText = None
    # while (inputText != "x"):
    #     print("options: \"spawn\": spawn, \"orders\": get orders json, \"x\": exit")
    #     inputText = input("input: ")

    #     if inputText == "x":
    #         subProcessManager.queue.put({
    #             "command": "stopProcess",
    #         })
    #         subProcessManager.join() # let subprocesses send last messages before quitting discord 
    #         pipeToDiscord.send({
    #             "stopProcess": 0,
    #         })
    #         discordSubprocess.join()
    #         print(TermColor.makeWarning("[END] SubProcess Manager ended"))
    #         continue
    #     elif inputText == "spawn":
    #         ticker = input(TermColor.makeBlue("[SPAWN PROMPT]") + " ticker: ")

    #         confirm = input(TermColor.makeBlue("[SPAWN PROMPT]") + " confirm? [Y/y/N/n]: ")
    #         if confirm.lower() == "y":
    #             try:
    #                 subProcessManager.queue.put({
    #                     "command": "spawn",
    #                     "ticker": ticker,
    #                 })
    #             except Exception as e:
    #                 print(TermColor.makeFail("[ERROR] failed to send data to pipe to spawn subprocess: " + str(e)))
    #         else:
    #             print(TermColor.makeBlue("[SPAWN PROMPT]") + " cancelling..")
        
    #     elif inputText == "orders":
    #         orders = api.orders_v2(account_id=account_id)
    #         print("orders: ", orders)
        
    #     elif inputText == "delay":
    #         SECONDS_THREAD_SLEEP = float(input("how many seconds?: "))
        
    #     elif inputText == "analysis":
    #         ticker = input(TermColor.makeBlue("[ANALYSIS PROMPT]") + " analysis for what ticker? : ")
    #         printDayAnalysis(api, account_id, ticker)
        
    #     elif inputText == "positions":
    #         print(api.get_account_info_v2())

    print(TermColor.getColorfulText("bye bye have a blessed day")) 