import json
import pandas as pd
import datetime
from bandl.request import RequestUrl
from bandl.helper import get_date_range

#default params for url connection
DEFAULT_TIMEOUT = 5 # seconds
MAX_RETRIES = 2

class CoinbaseUrl:
    def __init__(self):
        self.BASE_URL = "https://api.pro.coinbase.com"
        self.HEADER =   {
                        'Content-Type': 'application/json',
                        }
        self.data_columns = ["OpenTime","Low","High","Open","Close","Volume"]

    def __interval_to_garanularity(self,internal):
        time_frame  = pd.Timedelta(internal)
        return time_frame.total_seconds()

    def get_candle_data_url(self,symbol,start,end,interval,dayfirst=False):
        #granularity represents to total seconds
        '''The granularity field must be one of the following values: {60, 300, 900, 3600, 21600, 86400}.
            Otherwise, your request will be rejected. These values correspond to timeslices representing one minute,
            five minutes, fifteen minutes, one hour, six hours, and one day, respectively.'''
        granularity = str(int(self.__interval_to_garanularity(interval)))
        str_start = pd.to_datetime(start,dayfirst=dayfirst).strftime('%Y-%m-%dT%H:%M:%S')
        str_end = pd.to_datetime(end,dayfirst=dayfirst).strftime('%Y-%m-%dT%H:%M:%S')
        url = self.BASE_URL+"/products/"+symbol+"/candles?start="+str_start+"&stop="+\
                str_end+"&granularity="+granularity
        return url

class Coinbase:
    def __init__(self,api_key=None, api_secret=None,timeout=DEFAULT_TIMEOUT,max_retries=MAX_RETRIES):
        #internal initialization
        self.__request = RequestUrl(timeout,max_retries)
        self.urls = CoinbaseUrl()

    def get_data(self,symbol,start=None,end=None,periods=None,interval="1D",dayfirst=False):
        """Coinbase getData API for intraday/Historical data

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

            #capitalize symbol
            symbol = symbol.upper()
            data_url = self.urls.get_candle_data_url(symbol,start=s_from,end=e_till,interval=interval)
            res = self.__request.get(data_url,headers=self.urls.HEADER)
            data = json.loads(res.text)
            dfs = pd.DataFrame(data,columns=self.urls.data_columns)
            dfs['OpenTime'] = pd.to_datetime(dfs['OpenTime'], unit='s')
            dfs.set_index("OpenTime",inplace=True)
            return dfs

        except Exception as err:
            raise Exception("Error occurred while fetching data :", str(err))