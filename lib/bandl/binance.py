from bandl.request import RequestUrl

#default params for url connection
DEFAULT_TIMEOUT = 5 # seconds
MAX_RETRIES = 2

class BinanceUrl:
    def __init__(self):
        self.BASE_URL = "https://api.binance.com"

class Binance:
    def __init__(self,api_key, api_secret,timeout=DEFAULT_TIMEOUT,max_retries=MAX_RETRIES):
        #internal initialization
        self.__request = RequestUrl(timeout,max_retries)
        self.urls = BinanceUrl()