from bandl.request import RequestUrl
from bandl.helper import get_date_range

#default params for url connection
DEFAULT_TIMEOUT = 5 # seconds
MAX_RETRIES = 2

class BinanceUrl:
    def __init__(self):
        self.BASE_URL = "https://api.binance.com"
        self.DATA_URL = "https://api.binance.com/api/v3/klines?symbol="

class Binance:
    def __init__(self,api_key, api_secret,timeout=DEFAULT_TIMEOUT,max_retries=MAX_RETRIES):
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
            interval = interval.upper()
            #to be added

        except Exception as err:
            raise Exception("Error occurred while fetching data :", str(err))