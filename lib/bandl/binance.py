import json
import pandas as pd
import datetime

from bandl.request import RequestUrl
from bandl.helper import get_date_range

#default params for url connection
DEFAULT_TIMEOUT = 5 # seconds
MAX_RETRIES = 2

class BinanceUrl:
    def __init__(self):
        self.BASE_URL = "https://api.binance.com"
        self.DATA_URL = "https://api.binance.com/api/v3/klines?symbol="
        self.HEADER =   {
                        'Content-Type': 'application/json',
                        }
        self.data_columns = ["OpenTime","Open","High","Low","Close","Volume","CloseTime",\
                            "QuoteAssetVolume","NumberOfTrades","TakerBuyBaseAssetVolume",\
                            "TakerBuyQuoteAssetVolume","Ignore"]

    def get_candle_data_url(self,symbol,start,end,interval):
        return self.DATA_URL + symbol + "&startTime="+ start + "&endTime=" + end + "&interval=" + interval


class Binance:
    def __init__(self,api_key=None, api_secret=None,timeout=DEFAULT_TIMEOUT,max_retries=MAX_RETRIES):
        #internal initialization
        self.__request = RequestUrl(timeout,max_retries)
        self.urls = BinanceUrl()

    def get_data(self,symbol,start=None,end=None,periods=None,interval="1D",dayfirst=False):
        try:
            s_from,e_till = get_date_range(start=start,end=end,periods=periods,dayfirst=dayfirst)
            if s_from > e_till:
                raise ValueError("End should grater than start.")

            #capitalize
            symbol = symbol.upper()
            interval = interval.lower()

            s_from_milli_sec = str(int(s_from.timestamp() * 1000))
            e_till_milli_sec = str(int(e_till.timestamp() * 1000))

            data_url = self.urls.get_candle_data_url(symbol,start=s_from_milli_sec,end=e_till_milli_sec,interval=interval)
            res = self.__request.get(data_url,headers=self.urls.HEADER)
            data = json.loads(res.text)
            dfs = pd.DataFrame(data,columns=self.urls.data_columns)
            dfs['OpenTime'] = pd.to_datetime(dfs['OpenTime'], unit='ms')
            dfs['CloseTime'] = pd.to_datetime(dfs['CloseTime'], unit='ms')
            return dfs

        except Exception as err:
            raise Exception("Error occurred while fetching data :", str(err))