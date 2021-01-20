from datetime import datetime,timedelta
import pandas as pd
import io
import time

from bandl.helper import get_formated_date,get_date_range,is_ind_index
from bandl.request import RequestUrl
#default params for url connection
DEFAULT_TIMEOUT = 5 # seconds
MAX_RETRIES = 3


class Yfinance:
    def __init__(self,timeout=DEFAULT_TIMEOUT,max_retries=MAX_RETRIES):
        self.__yfinance_base_url = r"https://query1.finance.yahoo.com/v7/finance/download/"
        self.__yfinance_suffix_url = r"&interval=1d&events=history&includeAdjustedClose=true"
        self.__headers =  {'User-Agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/81.0.4044.138 Safari/537.36"}
        #create request
        self.__request = RequestUrl(timeout,max_retries)
        #ticker symbol map to yahoo finance:
        self.INDEX_MAP = {"SENSEX":"%5EBSESN","NIFTY 50":"%5ENSEI","NIFTY":"%5ENSEI",\
                           "NIFTY BANK":"%5ENSEBANK","BANKNIFTY":"%5ENSEBANK"}

    def __get_complete_url(self,symbol,start,end,is_indian=True):
        period1=int(time.mktime(start.timetuple()))
        period2=int(time.mktime(end.timetuple()))
        symbol = symbol.upper()
        if is_indian and is_ind_index(symbol):
            symbol  = self.INDEX_MAP.get(symbol)
            if not symbol:
                raise Exception("Data not available for this symbol")
        elif(is_indian):
            symbol += ".NS"

        complete_csv_url = self.__yfinance_base_url + symbol +'?period1='+str(period1)+'&period2='+str(period2)+self.__yfinance_suffix_url
        return complete_csv_url


    def get_data(self,symbol,is_indian=True,start=None,end=None,periods=None,dayfirst=False):
        """get_data API to fetch data from nasdaq

        :param symbol: stock symbol
        :type symbol: string
        :param start: start date, defaults to None
        :type start: string, optional
        :param end: end date, defaults to None
        :type end: string, optional
        :param is_indian: False if stock is not from indian market , defaults to True
        :type is_indian: bool, optional
        :param periods: number of days, defaults to None
        :type periods: integer, optional
        :param dayfirst: True if date format is european style DD/MM/YYYY, defaults to False
        :type dayfirst: bool, optional
        :raises ValueError: for invalid inputs
        :raises Exception: incase if no data found
        :return: stock data
        :rtype: pandas.DataFrame
        """
        #Step1: get the date range
        s_from,e_till = get_date_range(start=start,end=end,periods=periods,dayfirst=dayfirst)
        url = self.__get_complete_url(symbol,s_from,e_till,is_indian)
        response=self.__request.get(url,headers=self.__headers)
        dfs = pd.read_csv(io.StringIO(response.content.decode('utf-8')))
        dfs.set_index("Date",inplace=True)
        #convert to  datetime
        dfs.index = pd.to_datetime(dfs.index)
        dfs = self.__get_data_adjusted(dfs,symbol,start=start,end=end,periods=periods)
        if not dfs.empty:
            return dfs

    def __join_dfs(self,join,joiner):
        """will append joiner to join for oi_dfs

        :param join: df which will be appended
        :type join: pandas.DataFrame
        :param joiner: df which we want to append
        :type joiner: pandas.DataFrame
        :return: merged data frame
        :rtype: pandas.DataFrame
        """
        return join.append(joiner)

    def __get_data_adjusted(self,dfs,symbol,start=None,end=None,periods=None):
        if periods and (dfs.shape[0] < periods):
            new_periods = periods - dfs.shape[0]
            try:
                s_from = e_till = None
                #if only start, find till today
                if start and (not end):
                    s_from = dfs.index[0] + timedelta(1)
                    e_till = None
                #if not start, can go to past
                elif((end and (not start)) or periods):
                    s_from = None
                    e_till = dfs.index[0] - timedelta(1)
            except IndexError as err:
                raise Exception("yahoo finace Access error.")
            except Exception as exc:
                raise Exception("yahoo finace data error: ",str(exc))
            try:
                dfs_new = self.get_data(symbol,start = s_from,end = e_till,periods = new_periods)
                dfs = self.__join_dfs(dfs,dfs_new).sort_index(ascending=False)
            except Exception as exc:
                #Small part of data may not be available
                pass
        return dfs