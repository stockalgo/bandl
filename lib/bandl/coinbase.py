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
            #Todo
            return dfs

        except Exception as err:
            raise Exception("Error occurred while fetching data :", str(err))