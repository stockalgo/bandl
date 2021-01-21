import configparser
import json
import sys
from bandl.exception import InvalidFileError
from bandl.request import RequestUrl

#default params for url connection
DEFAULT_TIMEOUT = 5 # seconds
MAX_RETRIES = 2

from Crypto.Cipher import AES
import base64
from pbkdf2 import PBKDF2


class EncryptionClient:
    # Credit : https://github.com/5paisa/py5paisa/blob/master/py5paisa/auth.py
    def __init__(self,enc_key):
        self.iv = bytes([83, 71, 26, 58, 54, 35, 22, 11,
                         83, 71, 26, 58, 54, 35, 22, 11])
        self.enc_key = enc_key

    def _pad_and_convert_to_bytes(self, text):
        return bytes(text+chr(16-len(text) % 16)*(16-len(text) % 16), encoding="utf-8")

    def encrypt(self, text):
        padded_text = self._pad_and_convert_to_bytes(text)
        key_gen = PBKDF2(self.enc_key, self.iv)

        aesiv = key_gen.read(16)
        aeskey = key_gen.read(32)
        cipher = AES.new(aeskey, AES.MODE_CBC, aesiv)

        return str(base64.b64encode(cipher.encrypt(padded_text)), encoding="utf-8")



class FivePaisaURL:
    def __init__(self,email,password,dob,apikeys_filepath):
        self.LOGIN_URL=r"https://Openapi.5paisa.com/VendorsAPI/Service1.svc/V2/LoginRequestMobileNewbyEmail"
        self.LOGIN_HEADERS =  {'Content-Type': 'application/json'}
        config = configparser.ConfigParser()
        try:
            config.read(apikeys_filepath)
            self.__app_name = config["KEYS"]["APP_NAME"]
            self.__app_src =    config["KEYS"]["APP_SOURCE"]
            self.__used_id =    config["KEYS"]["USER_ID"]
            self.__password =   config["KEYS"]["PASSWORD"]
            self.__user_key =   config["KEYS"]["USER_KEY"]
            self.__encryption_key =config["KEYS"]["ENCRYPTION_KEY"]

        except Exception as err:
            raise InvalidFileError("API Keys configuration file is invalid")

        encryption_client = EncryptionClient(self.__encryption_key)
        self.LOGIN_PAYLOAD = {"head": {
            "appName": self.__app_name,
            "appVer": "1.0",
            "key": self.__user_key ,
            "osName": "WEB",
            "requestCode": "5PLoginV2",
            "userId": self.__used_id,
            "password": self.__password
            },
            "body":
            {
            "Email_id": encryption_client.encrypt(email),
            "Password": encryption_client.encrypt(password),
            "LocalIP": "",
            "PublicIP": "",
            "HDSerailNumber": "",
            "MACAddress": "",
            "MachineID": "039377",
            "VersionNo": "1.7",
            "RequestNo": "1",
            "My2PIN": encryption_client.encrypt(dob),
            "ConnectionType": "1"
            }
        }

class FivePaisa():
    def __init__(self,email,password,dob,apikeys_filepath,timeout=DEFAULT_TIMEOUT,max_retries=MAX_RETRIES):
        self.urls = FivePaisaURL(email,password,dob,apikeys_filepath)
        #internal initialization
        self.__request = RequestUrl(timeout,max_retries)
        #lets login
        res = self.__request.post(self.urls.LOGIN_URL,
                            data=json.dumps(self.urls.LOGIN_PAYLOAD),
                            headers = self.urls.LOGIN_HEADERS, verify=False)

        self.login_res = json.loads(res.text)
