import sys
import requests
from datetime import datetime
import re
import time
import logging
import json

KEYPATTERN = re.compile("<dt><span>(.+?)<\/span><\/dt>", flags=re.DOTALL | re.UNICODE)
KEYPATTERN2 = re.compile("<dt>(.+?)<\/dt>", flags=re.DOTALL | re.UNICODE)
VALSPATTERN = re.compile('<dd><span>(.+?)<\/span><\/dd>', flags=re.DOTALL | re.UNICODE)
VALSPATTERN2 = re.compile('<dd>(.+?)<\/dd>', flags=re.DOTALL | re.UNICODE)
TIMEPATTERN = re.compile('<h2 class="fLeft upperCase">Aktiedata<\/h2>.+?([0-9|\-]*)<\/span>', flags=re.DOTALL | re.UNICODE)

stock_data_keys = [
            'SHORT_NAME', #Kortnamn
            'ISIN',#ISIN
            'MARKET', #Marknad
            'INDUSTRY', #Bransch
            'CURRENCY', #Handlas i
            'BETA', # Beta
            'VOLATILITY', #Volatilitet %
            'LEVERAGE', #Belåningsvärde %
            'SAFETY', #Säkerhetskrav %
            'SUPER_INTEREST', #Superränta
            'SHORT_SALES', #Blankningsbar
            'SHARES_CNT', #Antal aktier
            'MARKET_CAP', #Börsvärde MSEK
            'YIELD', #Direktavkastning %
            'PE', #P/E-tal
            'PS', #P/S-tal
            'PB', #Kurs/eget kapital
            'RS', #Omsättning/aktie SEK
            'GS', #Vinst/aktie SEK
            'ES', #Eget kapital/aktie SEK
            'SS', #Försäljning/aktie SEK
            'ACTUAL_YIELD', #Effektivavkastning %
            'OWNERS' #Antal ägare hos Avanza
        ]
stock_Accounting_keys = [
            'ACCOUNTING_DATE',                       # Datum för årsredovisning
            'INTEREST_COVERAGE',                    # Räntetäckningsgrad
            'RETURN_ON_EQUITY',                     # Räntabilitet eget kapital %
            'Current_ratio',                        # Balanslikviditet
            'RETURN_ON_TOTAL_CAPITAL',              # Räntabilitet totalt kapital %
            'QUICK_RATIO',                          # Kassalikviditet
            'CHANGE_IN_EQUITY',                     # Ändring eget kapital %
            'SOLIDITY',                             # Soliditet 
            'CHANGE_IN_TOTAL_CAPITAL',              # Ändring totalt kapital%
            'ASSET_TURNOVER',                        # Kapitalomsättningshast
            'GROSS_MARGIN',                          # Bruttomarginal % 
            'INVENTORY_TURNOVER_RATE',               # Varulagrets oms. hast.
            'OPERATING_MARGIN',                      # Rörelsemarginal %
            'ACCOUNTS_RECEIVABLE_TURNOVER_RATE',     # Kundfordringar oms. hast.
            'NET_MARGIN',                            # Nettomarginal %
            'SHARE_OF_DISTRIBUTED_PROFIT'           # Andel utdelad vinst %
        ]

stock_data_keys_ConverterSpecial = ['ES','RS','GS','SS','MARKET_CAP']

class Avanza():
    site = "https://avanza.se"
    orderbookURL = f'{site}/ab/component/highstockchart/getchart/orderbook'
    stockUrl = f'{site}/aktier/om-aktien.html'
    stockAccountingUrl = f'{site}/aktier/om-bolaget.html'
    forumUrl = f'{site}/placera/forum/forum'
    forumStartUrl = f'{site}/placera/forum/start.'
    forumPageLimit = f'{site}/forum/user-preferences/posts-per-page'

    def __init__(self, client):
        self.pageLimit = 15 # Still not working with 200
        self.db = client
        self.session = requests.Session()
        self.session.head(self.forumStartUrl + "html")
        self.session.post(self.forumPageLimit, data={'posts': self.pageLimit})
    
    @staticmethod 
    def findWithTags(post:str, startTag:str, endTag:str, index:int=0, *preTags) -> (str, int):
        """
        Search for context based on start and end tags

        Return
            tagContent
            endIndex
        """
        for tag in preTags:
            index = post.find(tag, index) + len(tag)

        startIndex = post.find(startTag, index) + len(startTag)
        endIndex = post.find(endTag, startIndex)
        
        if startIndex < len(startTag): 
            logging.debug(f"Could not find any data between tags result: -1")
            return None, None # If not found

        return post[startIndex:endIndex], endIndex
        
    def addPost(self, post:dict):
        "Store user, company and post to the database if they do not exist"
        
        stockID, stockName = self.scrapeCompanyId(post) 
        r = self.db.add({
            'Table':'post', 
            'user_id':post['USERID'], 
            'user_name':post['USERNAME'],
            'forum_name':post['FORUMID'], 
            'stock_id':stockID, 
            'stock_name':stockName,
            'post_id':post['ID'],
            'company_id':post['FORUMID'], 
            'time':post['TIME'], 
            'topic':post['TOPIC'], 
            'text':post['TEXT'] 
            })      

        
        if r.status_code < 300:
            return 'OK'
        return 'FAIL'

    def addStockInfo(self,forum_name:str, stockID:str, stockName:str, currency:str,companyInfo:dict, **content:dict) -> None:
        """TODO: Update info if out of date (Based on latest update time)"""
        # Doesnt handle EUR very well (NEED SALE TO BE DEFINED IN SEK or EURO)
        if len(companyInfo) == 0: return None
        try:
            currency = companyInfo['CURRENCY'] # In order to not remove currency from input 
        except Exception as e:
            logging.error(f"Currency in addStockInfo is unknown for {forum_name}")
        """
        if 'CURRENCY' in companyInfo:
            for key in stock_data_keys_ConverterSpecial:
                try:
                    companyInfo.update({key:convertCurrency(companyInfo['CURRENCY'],float(companyInfo[key]))})
                except Exception as e:
                    logging.debug(f"FAILED converting CURRENCY for {forum_name} key: {key} val: {companyInfo[key]} \n {e}")
                    companyInfo.update({key:None})
        """
    
        if companyInfo['INTROTIME'] == 'None': companyInfo['INTROTIME'] = None
        companyContent = {
            'Table':'company', 
            'forum_name':forum_name,
            'short_name':companyInfo['SHORT_NAME'],
            'intro_time':time.time(),#companyInfo['INTROTIME'],
            'isin':companyInfo['ISIN'],
            'market':companyInfo['MARKET'],
            'industry':companyInfo['INDUSTRY'],
            'currency':currency,
            'info_time':time.time()
        }    

        accountingContent = { 
            'Table':'accounting', 
            'forum_name':forum_name,
            'info_time':companyInfo['INFOTIME'], 
            'beta':companyInfo['BETA'], 
            'volatility':companyInfo['VOLATILITY'], 
            'leverage':companyInfo['LEVERAGE'], 
            'safety':companyInfo['SAFETY'], 
            'super_interest':companyInfo['SUPER_INTEREST'] == 'Nej', 
            'short_sales':companyInfo['SHORT_SALES'] =='Nej', 
            'shares_cnt':companyInfo['SHARES_CNT'], 
            'market_cap':companyInfo['MARKET_CAP'], 
            'yield':companyInfo['YIELD'], # If nej = 0 else 1
            'pe':companyInfo['PE'], 
            'ps':companyInfo['PS'], 
            'pb':companyInfo['PB'], 
            'rs':companyInfo['RS'], 
            'gs':companyInfo['GS'], 
            'es':companyInfo['ES'],
            'ss':companyInfo['SS'], 
            'actual_yield':companyInfo['ACTUAL_YIELD'], 
            'owners':companyInfo['OWNERS'], 
            'accounting_date':companyInfo['ACCOUNTING_DATE'], 
            'interest_coverage':companyInfo['INTEREST_COVERAGE'], 
            'return_on_equity':companyInfo['RETURN_ON_EQUITY'], 
            'current_ratio':companyInfo['Current_ratio'], 
            'return_on_total_capital':companyInfo['RETURN_ON_TOTAL_CAPITAL'], 
            'quick_ratio':companyInfo['QUICK_RATIO'],
            'change_in_equity':companyInfo['CHANGE_IN_EQUITY'], 
            'solidity':companyInfo['SOLIDITY'], 
            'change_in_total_capital':companyInfo['CHANGE_IN_TOTAL_CAPITAL'],
            'asset_turnover':companyInfo['ASSET_TURNOVER'], 
            'gross_margin':companyInfo['GROSS_MARGIN'], 
            'inventory_turnover_rate':companyInfo['INVENTORY_TURNOVER_RATE'], 
            'operating_margin':companyInfo['OPERATING_MARGIN'], 
            'accounts_receivable_turnover_rate':companyInfo['ACCOUNTS_RECEIVABLE_TURNOVER_RATE'],
            'net_margin':companyInfo['NET_MARGIN'], 
            'share_of_distributed_profit':companyInfo['SHARE_OF_DISTRIBUTED_PROFIT'], 
        }   
        companyContent = goInsideRabbitHole(companyContent, forum_name)  
        accountingContent = goInsideRabbitHole(accountingContent, forum_name)
        
        self.sendBatch([accountingContent,companyContent])

    def addStockOrders(self,forum_name:str, stockID:str, stockName:str, currency:str, companyInfo:dict, **content:dict) -> None:
        if companyInfo is None:  return
        order_time = datetime.today().strftime('%Y-%m-%d') + " "+ companyInfo['ORDER_TIME']
        order_time = time.mktime(time.strptime(order_time, '%Y-%m-%d %H:%M:%S'))

        if order_time: # TODO convert currency
            orderContent = {
                'Table':'order', 
                'forum_name':forum_name,
                'info_time':order_time,
                'dev_procent':companyInfo['ORDER_DEV'], 
                'dev_sek':companyInfo['ORDER_DEV_SEK'].split(" ")[0], 
                'buy':companyInfo['ORDER_BUY'], 
                'sell':companyInfo['ORDER_SELL'], 
                'latest':companyInfo['ORDER_LATEST'], 
                'highest':companyInfo['ORDER_HIGHEST'], 
                'lowest':companyInfo['ORDER_LOWEST'], 
                'volume':companyInfo['ORDER_AMOUNT'],     
            }
        orderContent = goInsideRabbitHole(orderContent, forum_name)

        self.sendBatch([orderContent, {
                'Table':'company',
                'forum_name':forum_name,
                'order_time':time.time()
            }])

    def sendCalenderInfo(self,forum_name:str, companyInfo:dict, **content:dict) -> None:
        companyInfo = goInsideRabbitHole(companyInfo, forum_name)

        for eventtime in companyInfo:
            key_time = convertTime(eventtime, resolution='DAY')
            if isinstance(companyInfo[eventtime], dict): # Assume  there is just two items
                r = self.db.add({
                    'Table':'calender', 
                    'forum_name': forum_name,
                    'distribution_share':companyInfo[eventtime]['DISTRIBUTION_SHARE'].split(" ")[0],
                    'distribution_deadline': companyInfo[eventtime]['DISTRIBUTION_DEADLINE'],
                    'event':'Utdelning',
                    'info_time':key_time
                })
                return 'OK'
            r = self.db.add({
                'Table':'calender', 
                'forum_name': forum_name,
                'event':str(companyInfo[eventtime]),
                'info_time':key_time
            })

            logging.debug(f"Adding Calender response : {r.status_code}")
    

    def addGraphInfo(self, params) -> None:
        """
        Get information from scrapeGraph and combine new graph data with existing in database
        Params
            COMPANYID: ID of company
            STOCKID: ID for company stocks
            resolution: Can be defined as MINUTE, HOUR, DAY, MONTH
            timePeriod: Can be defined as day, week, month, year
        """
        
        logging.debug(f"Adding Graph response : {r.status_code}")
        return 'OK'

    def getPost(self, massiveString:str, postID:int):
        "Get the data from a specific userpost"

        preTag = f'<div class="userPost" id="{postID}">'
        startTag = '<div class="forumBox clearFix lhNormal forumPostText SText">'
        endTag = '</div>'
        result, _ = self.findWithTags(massiveString, startTag, endTag, 0, preTag)
        return result.lstrip()
    
    def scrapePageCount(self, index:int) -> (int,int):
        """
        Count the number of total pages on forum site
        """
        massiveString, newPageIndex = self.nextPage(index)
        cntPages,_ = self.findWithTags(massiveString, '<span class="bold">1/', '</span>', index=0)
        return cntPages,newPageIndex
    
    def scrapeForum(self, pageIndex:int=0, lastDBPost=0, batch_size=50) -> None:
        """
        Scrape forum, collect the posts and metadata and update database.

        Params
            pageIndex: Which page the scrape should start on the forum
            fullRun: If the forum shall run all posts or run till last seen in db
        """
        self.batch = []
        def commitPost(post):
            #print("Starting batch of commit", len(self.batch))
            stockID, stockName = self.scrapeCompanyId(post) 
            postContent = {
                            'Table':'post', 
                            'user_id':post['USERID'], 
                            'user_name':post['USERNAME'],
                            'forum_name':post['FORUMID'], 
                            'stock_id':stockID, 
                            'stock_name':stockName,
                            'post_id':post['ID'],
                            'company_id':post['FORUMID'], 
                            'time':post['TIME'], 
                            'topic':post['TOPIC'], 
                            'text':post['TEXT'] 
                    }
            self.batch.append(postContent)

        startTag = '<tr class="forumPyjamasRow">'
        endTag = '</tr>'
        endIndex = 0
        post = {'TIME': time.time()}
        massiveString, pageIndex = self.nextPage(pageIndex)
        batch_size = batch_size
        while lastDBPost <= post['TIME']:
            tagData, endIndex = self.findWithTags(massiveString, startTag, endTag, index=endIndex)

            if tagData is None: 
                # At end of page send batch
                endIndex = 0
                massiveString, pageIndex = self.nextPage(pageIndex)

                continue

            postMeta = self.scrapePost(tagData)
            post = {'TEXT':self.getPost(massiveString, postMeta['ID'])}
            post.update(postMeta)
            print(f"Adding post {post['ID']}!")
            logging.debug(f"Added Post: {post['ID']} to DB")

            # TODO: This part should be threaded...
            if len(self.batch) > batch_size:
                self.batch = self.sendBatch(self.batch)
            else: 
                self.db.threader(commitPost, post)

        self.sendBatch(self.batch)
        logging.info("Finished scraping Forum!")
        #return post
        

    def scrapePost(self, post:str):
        "Scrape overview data from each post"

        dictKeys = ['ID','TOPIC','FORUMID','FORUM','USERID','USERNAME','TIME']
        startTags = ['<td><a href="#','">','<td><a href="','">','<td><a href="','">','<td class="noWrap">']
        endTags = 3*['">','</a>']+['</td>']
        endIndex = 0
        meta = {}
        for dictKey, startTag, endTag in zip(dictKeys, startTags, endTags):
            val, endIndex = self.findWithTags(post, startTag, endTag, index=endIndex)
            meta.update({dictKey:val})
    
        # Small cleanup of input
        meta['FORUMID'],_ = self.findWithTags(str(meta['FORUMID']), '/placera/forum/forum/','.html')
        meta['USERID'],_ = self.findWithTags(str(meta['USERID']), 'anvandare.','.html')
        meta['TIME'] = convertTime('20' + meta['TIME'])
        
        return meta

    def scrapeCompanyId(self, post:dict) -> (int,str):
        "Extract id of company if ID exists otherwise it returns None"
        x = requests.get(f"{self.forumUrl}/{post['FORUMID']}.html")
        massiveString = x.content.decode('utf-8')

        companyInfo, _ = self.findWithTags(massiveString, '<a href="/handla/aktier.html/kop/', '" title="', index=0)
        
        if companyInfo is None: return None,None
        companyID, companyName=companyInfo.split('/')

        return int(companyID), companyName

    def scrapeStockInfo(self, forum_name:str, stockID:str, stockName:str) -> dict:
        """
        Extract information of company, 
        """
        if not stockID: 
            logging.debug(f"StockID is empty - Abort scrape of StockInfo for: {forum_name}")
            return None

        companyInfo = {}
        siteData = self.session.get(f'{self.stockUrl}/{str(stockID)}/{stockName}')
        massiveString = siteData.content.decode('utf-8')

        content_tags = {
            'ORDER_DEV':('<span class="XSText">Utv. idag %<br/>','</span>'),
            'ORDER_DEV_SEK':('<span class="XSText">Utv. idag','</span>'),
            'ORDER_BUY':('<span class="XSText">Köp<br/>','</span>'),
            'ORDER_SELL':('<span class="XSText">Sälj<br/>','</span>'),
            'ORDER_LATEST':('<span class="lastPrice SText bold">','title="Senast'),
            'ORDER_HIGHEST':('<span class="XSText">Högst<br/>','</span>'),
            'ORDER_LOWEST':('<span class="XSText">Lägst<br/>','</span>'),
            'ORDER_AMOUNT':('<span class="totalVolumeTraded SText','bold'),
            'ORDER_TIME':('<span class="updated SText', 'bold')
        }
        endIndex = 0
        try:
            for key, items in content_tags.items():
                startTag, endTag = items
                content, endIndex = self.findWithTags(massiveString,startTag, endTag, index=endIndex)
                content, endIndex = self.findWithTags(massiveString,'">', '</span>', index=endIndex)

                if content == None: continue
                companyInfo.update({key:content})

            vals = VALSPATTERN.findall(massiveString)

            timeInfo = TIMEPATTERN.findall(massiveString).pop()
            if timeInfo == '-': timeInfo = 0
            else: timeInfo = time.mktime(time.strptime(str(timeInfo), '%Y-%m-%d')) 

            companyInfo.update(dict(zip(stock_data_keys, vals)))
            companyInfo.update({'INFOTIME':timeInfo})
            return companyInfo
        except Exception as e:
            logging.error(f"Could not download stock info for: {forum_name} Error: {e}")
            return {}
        
    def scrapeStockAccounting(self, forum_name:str, stockID:str, stockName:str) -> dict:
        """
        Accounting data of company
        """

        if not stockID: 
            logging.debug(f"StockID is empty - Abort scrape of Accounting for: {companyID}")
            return None


        companyInfo = {}
        siteData = self.session.get(f'{self.stockAccountingUrl}/{str(stockID)}/{stockName}')
        massiveString = siteData.content.decode('utf-8')

        # Nyckeltal / KEY_FIGURES
        key_figures_Tags = {
            'KEY_FIGURES': ('<dl class="border XSText rightAlignText noMarginTop highlightOnHover thickBorderBottom noTopBorder">', '</div>')
        }
        endIndex = 0
        try:
            for key, itemTag in key_figures_Tags.items():
                startTag, endTag = itemTag 
                content, endIndex = self.findWithTags(massiveString, startTag, endTag, index=endIndex)
                if content == None: continue
                vals = VALSPATTERN.findall(content)
                companyInfo.update(dict(zip(stock_Accounting_keys ,vals)))
            
            #OTHER

            startTag, endTag = ('<dt>Introdatum</dt>', '</dl>')
            content, endIndex = self.findWithTags(massiveString, startTag, endTag, index=0)

            companyInfo.update({'INTROTIME':convertTime(*VALSPATTERN2.findall(content), resolution='DAY')})

            return companyInfo
        except Exception as e:
            logging.error(f"Could not download accounting data for: {forum_name} Error: {e}")
            return {}
            
    def scrapeCalenderEvents(self, forum_name:str, stockID:str, stockName:str) -> dict:
        """
        Events happening on the company
        """
        if not stockID: 
            logging.debug(f"StockID is empty - Abort scrape of CalenderEvents for: {forum_name}")
            return None

        companyInfo = {}
        siteData = self.session.get(f'{self.stockAccountingUrl}/{str(stockID)}/{stockName}')
        massiveString = siteData.content.decode('utf-8')
        
        # Company Calender (kommande och tidigare -> händelse, tid)
        
        calender_Tags = {
            'UPCOMMING_CALENDER_EVENTS':('<h3 class="bold">Kommande händelser</h3>','<h3 class="bold">Tidigare händelser</h3>'),
            'PREVIOUS_CALENDER_EVENTS':('<h3 class="bold">Tidigare händelser</h3>','<div class="company_balance_sheet">')
        }
        calender_distribution_Tags = {
            'DISTRIBUTION_SHARE':('Utdelning/aktie: ','</li>'),
            'DISTRIBUTION_DEADLINE': ('Handlas utan utdelning: ', '</li>')
        }
        diff_distribution_names = ['Distribution av värdepapper', 'Ordinarie utdelning', 'Bonusutdelning']
        endIndex = 0
        for key, item in calender_Tags.items():
            startTag, endTag = item 
            content, endIndex = self.findWithTags(massiveString, startTag, endTag, index=endIndex)
            
            if content == None: continue
            # In case data contains "Utdelning"
            keys = KEYPATTERN.findall(content)
            vals = VALSPATTERN.findall(content)

            calenderInfo = dict(zip(keys,vals))
            
            for key, val in zip(keys,vals):
                for special_dist in diff_distribution_names:
                    if special_dist in val:
                        endIndex1 = 0
                        tempDict = {}
                        for key1, item1 in calender_distribution_Tags.items():
                            startTag1, endTag1 = item1
                            content, endIndex1 = self.findWithTags(val, startTag1, endTag1, index=endIndex1)
                            #calenderInfo.pop(key)
                            tempDict.update({key1:content})
                        calenderInfo.update({key:tempDict})

            self.sendCalenderInfo(forum_name,calenderInfo)
        #return calenderInfo
    
    def scrapeNews(self):
        pass
    
    def scrapeGraph(self, forum_name:str, stockID:int, resolution:str="HOUR", timePeriod:str='month', compareIds:list=['19002']) -> dict: 
        """ 
        Extract data of given graph based on parameters above. Return a dictionary of value and unix time.
        If it is the daily extraction then go for resolution day (HOUR) otherwise month (Hour)

        Params:
            stockID: The id given with the stock
            resolution: Choose between HOUR, MINUTE, DAYS, MONTH should be compatible with timePeriod
            timePeriod: Which period should be observed. day, month, year, max

        Return: Dictionary containing datapoints for company stock value and OMXS30.
        """
        if not stockID: 
            logging.debug("StockID is empty")
            return None

        orderbook_request = {
            "orderbookId":stockID,
            "chartType":"AREA",
            "widthOfPlotContainer":'558',
            "chartResolution":resolution,
            "navigator":'true',
            "percentage":'false',
            "volume":'false',
            "owners":'false',
            "timePeriod":timePeriod,
            "ta":[],
            "compareIds":compareIds
        }
        p = requests.post(self.orderbookURL, json=orderbook_request)
    
        if p.status_code != 200:
            logging.error(f"Wrong status code! Code: {p.status_code} Input: {stockID} {resolution} {timePeriod}")
            return None
        if p.json() is None: 
            print(f"No data was gathered from site: {stockID}!")
            return None
        
        self.sendBatch([{
                'Table':'graph',
                'forum_name':forum_name,
                'graph':p.json()['dataPoints']
            },{
                'Table':'company',
                'forum_name':forum_name,
                'graph_time':time.time()
            }
        ])
        
    def nextPage(self, pageIndex:int) -> (str, int):
        """
        Move to a new page based pageIndex and number of posts on the site

        Params
            pageIndex: At which page the request shall be made on

        Return
            massiveString: Massive string containing all data
            newPage: Number at which the new side will be on

        """
        x = self.session.get(self.forumStartUrl + str(pageIndex) + ".html")
        massiveString = x.content.decode('utf-8')
        newPageIndex = pageIndex + self.pageLimit
        logging.debug(f"New pageIndex at: {newPageIndex} old data: {pageIndex} {self.pageLimit}")
        return massiveString, newPageIndex

def convertTime(postTime:str, resolution='MINUTE') -> int:
    "Converts time date time to unix time"
    try:
        if resolution == 'MINUTE':
            return time.mktime(time.strptime(postTime, '%Y-%m-%d %H:%M')) 
        if resolution == 'DAY':
            return time.mktime(time.strptime(postTime, '%Y-%m-%d')) 

    except Exception as e:
        logging.debug(f"Could not convert time: '{postTime}'")
        return None

def convertCurrency(currency:str, amount:int) -> int:
    """
    Convert a currency into SEK. Python 3.7<
    Params
        currency: Specified currency in string. Example: EUR, SEK, NOR
        amount: The amount of money to be converted
    """
    
    if currency == 'SEK': return amount
    logging.debug(f"Convert {amount} from {currency} to SEK")
    return CurrencyConverter().convert(amount,currency,'SEK')

def localTokenRemover(content, key, companyID='Unknown') -> str:
    """
    Remove unwanted syntax from string
    """
    if content == '-' or content == None: 
        logging.debug(f"Contained invalid token: '{content}' for Company: {companyID} key: {key} ")
        return None
    
    # TODO needs to contain all possible currencies :(
    #"SEK", "NOK", "EUR", "USD","CAD",
    token_to_remove = ["%", "+", "<br />", u"\xa0", "\r", "\n","\t"]

    for curr in token_to_remove:
        content = content.replace(curr,"")

    content = content.replace(u',',u'.').strip()

    return content
            
def goInsideRabbitHole(post:str, companyID:str) -> str:
    """
    Recursive deepening of dictionary or list in order to reduce unwanted syntaxes
    """
    for key, post_content in post.items():
        if type(post_content) == dict or type(post_content) == list: 
            post_content = goInsideRabbitHole(post_content, companyID)
            continue
            
        post[key] = localTokenRemover(str(post_content), key, companyID)
    return post

def printProgress(index:int) -> None:
    "Print progress based on index value"
    if index % 100 == 0 and index != 0: logging.info(f"Progress: {index}")
