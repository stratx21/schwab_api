import datetime
from discord.ext import commands, tasks
import discord
import json
import random

from schwab_api import Schwab
from strategy.subprocess_management import SchwabManager
from tools.terminal_colors import TermColor




class DiscordUtils():
    def __init__(self, CONFIG_JSON_FILE_NAME, client):
        with open(CONFIG_JSON_FILE_NAME) as configFile:
            data = json.load(configFile)
            if "discord" in data.keys() and "channels" in data["discord"].keys():
                self._channelIds = data["discord"]["channels"]
            else:
                raise Exception(TermColor.makeFail("[ERROR] config file does not have discord channels!"))
        
        self.client = client
    
    def getChannel(self, channelName):
        try:
            return self.client.get_channel(self._channelIds[channelName])
        except Exception as e:
            print(TermColor.makeFail(f'[ERROR] failed to get channel in DiscordChannelsCollection.getChannel; Exception: {str(e)}'))
    
    def makeFix(self, text):
        return f"```fix\n{text}\n```"

    def makeGreen(self, text):
        return f"```css\n{text}\n```"
    
    def makeRed(self, text):
        return f"```css\n[{text}]\n```"







def runDiscordTerminalProcess(
        CONFIG_JSON_FILE_NAME,      # the config file for info 
        account_id,
        api: Schwab
        # pipeToFromApp,              # pipe to receive and send data from/to the app
        # subProcessManager: SubProcessManagingThreadWrapper      
):
    with open(CONFIG_JSON_FILE_NAME) as configFile:
        data = json.load(configFile)
        token = None
        ownerId = None
        if "discord" in data.keys():
            discordConfig = data["discord"]
            if "token" in discordConfig.keys():
                token = discordConfig["token"]
            if "ownerId" in discordConfig.keys():
                ownerId = discordConfig["ownerId"]
    
    if ownerId == None:
        print(TermColor.makeGreen("[DISCORD] owner discord ID not provided in config. Please provide owner id for access to commands"))
    if token == None:
        print(TermColor.makeGreen("[DISCORD] token not provided in config. Unable to start discord bot"))
        return 1

    intents = discord.Intents.default()
    intents.message_content = True

    client = commands.Bot("!", intents=intents, owner_id=ownerId)

    discordUtils = DiscordUtils(CONFIG_JSON_FILE_NAME, client)
    logsChannel = None

    appManager = SchwabManager(account_id, api)
    
    @tasks.loop(seconds=1)
    async def timer():
        logsChannel = discordUtils.getChannel("logs")
        while appManager.pollAppPipe(): # has data
            data = appManager.receiveFromAppPipe()
            # await generalChannel.send(f'data from pipe to discord: {str(data)}')

            if "stopProcess" in data.keys():
                await logsChannel.send('Stopping discord process. End process status is normal.')
                return 0
            if "stopProcessSuccess" in data.keys():
                await logsChannel.send(f'[COMMAND] [{datetime.datetime.now().strftime("%I:%M:%S%p on %D")}] successfully stopped process for ticker {data["stopProcessSuccess"]}.')
            if "rareError" in data.keys():
                tickerstr = (f' [{data["ticker"]}]') if ("ticker" in data.keys() and data["ticker"] != None) else ""
                importantChannel = discordUtils.getChannel("important")
                await logsChannel.send(f'[RARE ERROR]{tickerstr} {data["rareError"]}')
                await importantChannel.send(f'[RARE ERROR]{tickerstr} {data["rareError"]}')
            if "error" in data.keys():
                tickerstr = (f' [{data["ticker"]}]') if "ticker" in data.keys() else ""
                await logsChannel.send(f'[ERROR]{tickerstr} {data["error"]}')
                




    @client.event
    async def on_ready():
        print(f'Logged in to discord as {client.user}')
        timer.start()

    @client.event
    async def on_message(message):
        if message.author != client.user:
            if message.content.startswith('$hello'):
                await message.channel.send('Hello!')
        
        await client.process_commands(message)
    
    @client.command(aliases = ['RAgent', 'ragent', 'RandomAgent', 'randomagent'])
    async def Random_Agent_Selection(ctx):
        Agents = ['Breach',
                'Brimstone',
                'Cypher',
                'Jett',
                'Killjoy',
                'Omen',
                'Phoenix',
                'Raze',
                'Reyna',
                'Sage',
                'Skye',
                'Sova',
                'Viper']
        await ctx.channel.send(f"Random Agent: {random.choice(Agents)}")

    @client.command(aliases = ['startTicker', 'startProcess', 'spawnProcess', 'spawnTicker', 'start', 'START', 'SPAWN'])
    @commands.is_owner()
    async def spawn(
        ctx,
        ticker: str = None,
        profitMargin = 0.03,
        timeBeforeCancel = 3,
        minBASpread = 0.1,
        qty = 1,
        maintainedEquity = 1
    ):
        """Spawn new scraping process for specified ticker"""
        if ticker == None:
            await ctx.channel.send(discordUtils.makeFix("[COMMAND ERROR] must include ticker for spawn command!"))
            return
        ticker = ticker.upper()

        success = appManager.spawn(ticker, profitMargin, maintainedEquity, minBASpread, qty, timeBeforeCancel)
        
        if success: 
            await ctx.channel.send(discordUtils.makeGreen("[COMMAND] successfully started scraper process for \"" + ticker + "\""))
        else:
            await ctx.channel.send(discordUtils.makeRed("[ERROR] error starting scraper process for \"" + ticker + "\""))
    
    @client.command(aliases = ['startOCO', 'startoco', 'spawnWTrailingStop', 'spawnoco'])
    @commands.is_owner()
    async def spawnOCO(
        ctx,
        ticker: str = None,
        profitMargin = 0.03,
        trailingStopDollars = 0.07,
        minBASpread = 0.1,
        qty = 1,
        maintainedEquity = 1
    ):
        """Spawn new scraping process for specified ticker"""
        if ticker == None:
            await ctx.channel.send(discordUtils.makeFix("[COMMAND ERROR] must include ticker for spawn command!"))
            return
        ticker = ticker.upper()

        success = appManager.spawnWTrailingStop(ticker, profitMargin, maintainedEquity, minBASpread, qty, trailingStopDollars)
        
        if success: 
            await ctx.channel.send(discordUtils.makeGreen("[COMMAND] successfully started scraper with OCO process for \"" + ticker + "\""))
        else:
            await ctx.channel.send(discordUtils.makeRed("[ERROR] error starting scraper with OCO process for \"" + ticker + "\""))
    
    @client.command(aliases = ['getOrders',])
    @commands.is_owner()
    async def orders(
        ctx,
    ):
        """Get open orders info"""

        orders = appManager.getOpenOrders()
        
        # if orders != None: 
        #     await ctx.channel.send(discordUtils.makeGreen("[COMMAND] orders: " + str(orders)))
        # else:
        #     await ctx.channel.send(discordUtils.makeRed("[ERROR] error getting orders"))

    @client.command(aliases = ['stopTicker','stopStrat'])
    @commands.is_owner()
    async def stop(ctx, ticker = None):
        """Stops scraping for specified ticker"""
        if ticker == None:
            await ctx.channel.send(discordUtils.makeFix("[COMMAND ERROR] must include ticker for stop command!"))
            return
        ticker = ticker.upper()

        appManager.stopTicker(ticker)
        
        # if success: 
        #     await ctx.channel.send(discordUtils.makeGreen("[COMMAND] successfully stopped scraper process for \"" + ticker + "\""))
        # else:
        #     await ctx.channel.send(discordUtils.makeRed("[ERROR] error stopping scraper process for \"" + ticker + "\". Maybe it doesn't exist?"))
    
    @client.command(aliases = ['kill',])
    @commands.is_owner()
    async def exit(ctx):
        """exit the program entirely, and log out of Schwab"""
        appManager.stopAll()
        await ctx.channel.send(discordUtils.makeGreen("Stopped! Byebye!"))
        await ctx.bot.close()

    
    client.run(token) # blocking 

    
    

