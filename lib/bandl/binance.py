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
        self.BASE_URL = "https://api.binance.com/"
        self.BACKUP_URL = "https://api3.binance.com/"
        self.HEADER =   {
                        'Content-Type': 'application/json',
                        }
        self.data_columns = ["OpenTime","Open","High","Low","Close","Volume","CloseTime",\
                            "QuoteAssetVolume","NumberOfTrades","TakerBuyBaseAssetVolume",\
                            "TakerBuyQuoteAssetVolume","Ignore"]
        self.TICKER_URL= "https://www.binance.com/api/v1/ticker/allPrices"

    def get_candle_data_url(self,symbol,start,end,interval,use_backup=False):
        url = self.BASE_URL
        if use_backup:
            url = self.BACKUP_URL
        return url + "api/v3/klines?symbol="+ symbol + "&startTime="+ start + "&endTime=" + end + "&interval=" + interval


class Binance:
    def __init__(self,api_key=None, api_secret=None,timeout=DEFAULT_TIMEOUT,max_retries=MAX_RETRIES):
        #internal initialization
        self.__request = RequestUrl(timeout,max_retries)
        self.urls = BinanceUrl()

    def get_tickers(self,keyword="None"):
        """Get all crypto tickers from binance

        :param keyword: Any keyword to match, for ex. "BTC" will return all BTC pair, defaults to "None"
        :type keyword: str, optional
        :raises Exception: related to network/API
        :return: list of all tickers form binance
        :rtype: list
        """
        try:
            res = self.__request.get(self.urls.TICKER_URL,headers=self.urls.HEADER)
            tickers = json.loads(res.text)
            all_tickers = [each_symbol.get("symbol") for each_symbol in tickers]
            if keyword:
                keyword = keyword.upper()
                all_tickers = [symbol for symbol in all_tickers if keyword in symbol]
            return all_tickers
        except Exception as err:
            raise Exception("Error occurred while getting tickers :", str(err))

    def get_data(self,symbol,start=None,end=None,periods=None,interval="1D",dayfirst=False):
        """Binance getData API for intraday/Historical data

        :param symbol: crypto symbol
        :type symbol: string
        :param start: start time, defaults to None
        :type start: string optional
        :param end: end time, defaults to None
        :type end: string, optional
        :param periods: No of days, defaults to None
        :type periods: integer, optional
        :param interval: timeframe, defaults to "1D"
        :type interval: string, optional
        :param dayfirst: if date in european style, defaults to False
        :type dayfirst: bool, optional
        :raises ValueError: invalid time
        :raises Exception: for execption
        :return: data requested
        :rtype: pandas.DataFrame
        """
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
            try:
                res = self.__request.get(data_url,headers=self.urls.HEADER)
            except:
                data_url = self.urls.get_candle_data_url(symbol,start=s_from_milli_sec,end=e_till_milli_sec,interval=interval,use_backup=True)
                res = self.__request.get(data_url,headers=self.urls.HEADER)

            data = json.loads(res.text)
            dfs = pd.DataFrame(data,columns=self.urls.data_columns)
            dfs['OpenTime'] = pd.to_datetime(dfs['OpenTime'], unit='ms')
            dfs['CloseTime'] = pd.to_datetime(dfs['CloseTime'], unit='ms')
            dfs.set_index("OpenTime",inplace=True)

            return dfs

        except Exception as err:
            raise Exception("Error occurred while fetching data :", str(err))