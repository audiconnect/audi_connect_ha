
import requests
import json

from audiapi.Token import Token

TIMEOUT = 10

class AudiAPI:
    """
    Wrapper for the audi API
    """
    BASE_URL = 'https://msg.audi.de/fs-car'
    BASE_CAR_URL = 'https://msg.audi.de/fs-car/bs/cf/v1/Audi/DE/vehicles'

    BASE_HEADERS = {'Accept': 'application/json',
                    'X-App-ID': 'de.audi.mmiapp',
                    'X-App-Name': 'MMIconnect',
                    'X-App-Version': '2.8.3',
                    'X-Brand': 'audi',
                    'X-Country-Id': 'DE',
                    'X-Language-Id': 'de',
                    'X-Platform': 'google',
                    'User-Agent': 'okhttp/2.7.4',
                    'ADRUM_1': 'isModule:true',
                    'ADRUM': 'isAray:true'}

    def __init__(self, proxy=None):
        """
        Creates a new API
        :param proxy: Proxy which should be used in the URL format e.g. http://proxy:8080
        """
        self.__token = None
        if proxy is not None:
            self.__proxy = {'http': proxy,
                            'https': proxy}
        else:
            self.__proxy = None

    def use_token(self, token: Token):
        """
        Uses the given token for auth
        :param token: Token
        """
        self.__token = token

    def get(self, url):
        r = requests.get(url, headers=self.__get_headers(), proxies=self.__proxy, timeout=TIMEOUT)
        return self.__handle_error(r.json())

    def put(self, url, data=None, headers=None):
        full_headers = self.__get_headers()
        full_headers.update(headers)
        r = requests.put(url, data, headers=full_headers, proxies=self.__proxy, timeout=TIMEOUT)
        return self.__handle_error(r.json())

    def post(self, url, data=None, use_json: bool = True):
        if use_json and data is not None:
            data = json.dumps(data)
        r = requests.post(url, data=data, headers=self.__get_headers(), proxies=self.__proxy, timeout=TIMEOUT)
        return self.__handle_error(r.json())

    def __handle_error(self, data):
        error = data.get('error')
        if error is not None:
            error_msg = data.get('error_description', '')
            raise Exception('API error: ' + str(error) + '\n' + error_msg)
        return data

    def __get_headers(self):
        full_headers = dict()
        full_headers.update(self.BASE_HEADERS)
        token_value = 'AudiAuth 1'
        if self.__token is not None:
            token_value += ' ' + self.__token.access_token
        full_headers['Authorization'] = token_value
        return full_headers