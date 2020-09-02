import sys
import requests
import re
import time
from client import client_logger
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
    request_timeout = 20
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
        
        if startIndex < len(startTag): return None, None

        return post[startIndex:endIndex], endIndex
    
    def requestContent(self,url):
        try:
            content = self.session.get(url, timeout=self.request_timeout)
            if content != None: return content.content.decode('utf-8')
        except:
            pass
        raise Exception(f"Website does not exist or request timed out! Url: {url}!")

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

    def scrapeForum(self, pageIndex:int=0, lastDBPost=0) -> None:
        """
        Scrape forum, collect the posts and metadata and update database.

        Params
            pageIndex: Which page the scrape should start on the forum
            fullRun: If the forum shall run all posts or run till last seen in db
        """
        
        startTag = '<tr class="forumPyjamasRow">'
        endTag = '</tr>'
        endIndex = 0
        post = {'TIME': time.time()}
        massiveString, pageIndex = self.nextPage(pageIndex)
        batch = []

        while True:
            
            tagData, endIndex = self.findWithTags(massiveString, startTag, endTag, index=endIndex)
            if tagData is None: break

            postMeta = self.scrapePost(tagData)
            post = {'TEXT':self.getPost(massiveString, postMeta['ID'])}
            post.update(postMeta)
            if lastDBPost > post['TIME']: return batch, True
            batch.append(post)
            
            client_logger.debug(f"Added Post: {post['ID']} to batch")
        return batch, False
        
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
        massiveString = self.requestContent(f"{self.forumUrl}/{post['FORUMID']}.html")

        companyInfo, _ = self.findWithTags(massiveString, '<a href="/handla/aktier.html/kop/', '" title="', index=0)
        
        if companyInfo is None: raise Exception(f"Could not find company id or company name FORUMID: {post['FORUMID']}")
        companyID, companyName=companyInfo.split('/')

        return int(companyID), companyName

    def scrapeStockInfo(self, forum_name:str, stockID:str, stockName:str) -> dict:
        """
        Extract information of company, 
        """
        if not stockID: raise Exception(f"StockID is empty - Abort scrape of StockInfo for: {forum_name}")

        companyInfo = {}
        massiveString = self.requestContent(f'{self.stockUrl}/{str(stockID)}/{stockName}')

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
            client_logger.error(f"Could not download stock info for: {forum_name} Error: {e}")
            return {}
        
    def scrapeStockAccounting(self, forum_name:str, stockID:str, stockName:str) -> dict:
        """
        Accounting data of company
        """

        if not stockID: raise Exception(f"StockID is empty - Abort scrape of Accounting for: {forum_name}")


        companyInfo = {}
        massiveString = self.requestContent(f'{self.stockAccountingUrl}/{str(stockID)}/{stockName}')

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
            try:
                companyInfo.update({'INTROTIME':convertTime(*VALSPATTERN2.findall(content), resolution='DAY')})
            except Exception as e:
                client_logger.error(f"Company: {forum_name}! Error: {e}. INTROTIME replaced with 0")
                companyInfo.update({'INTROTIME':0})

            return companyInfo
        except Exception as e:
            client_logger.error(f"Could not download accounting data for: {forum_name} Error: {e}")
            return {}

    def scrapeCalenderEvents(self, forum_name:str, stockID:str, stockName:str) -> dict:
        """
        Events happening on the company
        """
        if not stockID: raise Exception(f"StockID is empty - Abort scrape of CalenderEvents for: {forum_name}")

        companyInfo = {}
        massiveString = self.requestContent(f'{self.stockAccountingUrl}/{str(stockID)}/{stockName}')
        
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
        calenderInfo = {}
        for key, item in calender_Tags.items():
            startTag, endTag = item 
            content, endIndex = self.findWithTags(massiveString, startTag, endTag, index=endIndex)
            
            if content == None: continue
            # In case data contains "Utdelning"
            keys = KEYPATTERN.findall(content)
            vals = VALSPATTERN.findall(content)

            calenderInfo.update(dict(zip(keys,vals)))
            
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
           
        return calenderInfo
    
    def scrapeCompanyURL(self):
        """
        Return all stock id's and stock names from avanza
        """
        content = []
        url = self.site + "/sitemap1.xml"
        massiveString = self.requestContent(url)
        searchString = re.compile('<loc>.+?om-aktien.html\/(.+?)\/(.+?)<\/loc>', flags=re.DOTALL | re.UNICODE)

        # Return list with stockID and stockName
        massiveList = searchString.findall(massiveString)

        return massiveList

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
        if not stockID: raise Exception(f"StockID is empty - Abort scrape of Graph for: {forum_name}")

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
    
        if p.status_code != 200: raise Exception(f"Wrong status code! Code: {p.status_code} Input: {stockID} {resolution} {timePeriod}")
        if p.json() is None: raise Exception(f"No data was gathered from site: {stockID}!")
        

        return [{
                'Table':'graph',
                'forum_name':forum_name,
                'graph':p.json()['dataPoints']
            },{
                'Table':'company',
                'forum_name':forum_name,
                'graph_time':time.time()
            }
        ]
  
    def nextPage(self, pageIndex:int) -> (str, int):
        """
        Move to a new page based pageIndex and number of posts on the site

        Params
            pageIndex: At which page the request shall be made on

        Return
            massiveString: Massive string containing all data
            newPage: Number at which the new side will be on

        """
        massiveString = self.requestContent(self.forumStartUrl + str(pageIndex*self.pageLimit) + ".html")
        newPageIndex = pageIndex + 1
        client_logger.debug(f"New pageIndex at: {newPageIndex} old data: {pageIndex} {self.pageLimit}")
        return massiveString, newPageIndex

def convertTime(postTime:str, resolution='MINUTE') -> int:
    "Converts time date time to unix time"

    if resolution == 'MINUTE':
        return time.mktime(time.strptime(postTime, '%Y-%m-%d %H:%M')) 
    if resolution == 'DAY':
        return time.mktime(time.strptime(postTime, '%Y-%m-%d')) 

    raise Exception(f"Could not convert time: '{postTime}' Resolution '{resolution}")