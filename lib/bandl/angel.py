import requests
import json
import socket

from bandl.request import RequestUrl

#default params for url connection
DEFAULT_TIMEOUT = 5 # seconds
MAX_RETRIES = 2

class AngelUrl:
    def __init__(self,api_key):
        self._BASE_URL = "https://apiconnect.angelbroking.com"
        hostname = socket.gethostname()
        client_local_ip = socket.gethostbyname(hostname)
        client_public_ip = RequestUrl().get('https://api.ipify.org').text

        self.routes =   {
                        "login":"/rest/auth/angelbroking/user/v1/loginByPassword"
                        }

        self.LOGIN_HEADERS = {
                        'Content-Type': 'application/json',
                        'Accept': 'application/json',
                        'X-UserType': 'USER',
                        'X-SourceID': 'WEB',
                        'X-ClientLocalIP': client_local_ip,
                        'X-ClientPublicIP': client_public_ip ,
                        'X-MACAddress': '00:00:00:00:00:00',
                        'X-PrivateKey': api_key
                        }

    def get_url(self,type):
        return self._BASE_URL + self.routes.get(type,None)

class Angel:
    def __init__(self,user_id,password,api_key,timeout=DEFAULT_TIMEOUT,max_retries=MAX_RETRIES):
        #internal initialization
        self.__request = RequestUrl(timeout,max_retries)
        self.urls = AngelUrl(api_key)

        request_body = {
                        "clientcode": user_id,
                        "password": password,
                        }

        #lets login
        res = self.__request.post(self.urls.get_url("login"),
                            data=json.dumps(request_body),
                            headers = self.urls.LOGIN_HEADERS)
        self.__login_res = json.loads(res.text)
        self.__feed_token = self.__login_res.get("data").get("feedToken",None)