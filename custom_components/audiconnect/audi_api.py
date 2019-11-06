
import requests
import json
import logging
from datetime import timedelta, datetime

from audiapi.Token import Token

import asyncio

from audiapi.API import Token, API

from aiohttp import ClientSession, ClientTimeout, BasicAuth
from aiohttp.hdrs import METH_GET, METH_POST, METH_PUT

TIMEOUT = timedelta(seconds=30)

_LOGGER = logging.getLogger(__name__)

class AudiAPI:
    def __init__(self, session, proxy=None):
        """
        Creates a new API
        :param proxy: Proxy which should be used in the URL format e.g. http://proxy:8080
        """
        self.__token = None
        self._session = session
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

    async def _request(self, method, url, data, headers, **kwargs):
        """Perform a query to the online service."""
        async with self._session.request(
            method,
            url,
            headers=headers,
            data=data,
            timeout=ClientTimeout(total=TIMEOUT.seconds),
            **kwargs
        ) as response:
            response.raise_for_status()
            res = await response.json(loads=json_loads)
            return res

    async def get(self, url):
        r = await self._request(METH_GET, url, data=None, headers=self.__get_headers())
        return r

    async def put(self, url, data=None, headers=None):
        full_headers = self.__get_headers()
        full_headers.update(headers)
        r = await self._request(METH_PUT, url, headers=headers, data=data)
        return r

    async def post(self, url, data=None, use_json: bool = True):
        if use_json and data is not None:
            data = json.dumps(data)
        r = await self._request(METH_POST, url, headers=self.__get_headers(), data=data)
        return r

    def __get_headers(self):
        full_headers = dict()
        full_headers.update(API.BASE_HEADERS)
        token_value = 'AudiAuth 1'
        if self.__token is not None:
            token_value += ' ' + self.__token.access_token
        full_headers['Authorization'] = token_value
        return full_headers


def obj_parser(obj):
    """Parse datetime."""
    for key, val in obj.items():
        try:
            obj[key] = datetime.strptime(val, "%Y-%m-%dT%H:%M:%S%z")
        except (TypeError, ValueError):
            pass
    return obj

def json_loads(s):
    return json.loads(s, object_hook=obj_parser)
