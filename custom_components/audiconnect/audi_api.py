import requests
import json
import logging
from datetime import timedelta, datetime

import traceback
import asyncio
import async_timeout

from asyncio import TimeoutError
from aiohttp import ClientSession, ClientResponseError
from aiohttp.hdrs import METH_GET, METH_POST, METH_PUT

TIMEOUT = 10

_LOGGER = logging.getLogger(__name__)


class AudiAPI:
    def __init__(self, session, proxy=None):
        self.__token = None
        self._session = session
        if proxy is not None:
            self.__proxy = {"http": proxy, "https": proxy}
        else:
            self.__proxy = None

    def use_token(self, token):
        self.__token = token

    async def request(self, method, url, data, headers, **kwargs):
        try:
            # print(url)
            with async_timeout.timeout(TIMEOUT):
                async with self._session.request(
                    method, url, headers=headers, data=data
                ) as response:
                    # print(response)
                    if response.status == 200 or response.status == 202:
                        return await response.json(loads=json_loads)
                    else:
                        raise ClientResponseError(
                            response.request_info,
                            response.history,
                            status=response.status,
                            message=response.reason,
                        )
        except TimeoutError:
            raise TimeoutError("Timeout error")
        except Exception:
            raise

    async def get(self, url):
        r = await self.request(METH_GET, url, data=None, headers=self.__get_headers())
        return r

    async def put(self, url, data=None, headers=None):
        full_headers = self.__get_headers()
        full_headers.update(headers)
        r = await self.request(METH_PUT, url, headers=headers, data=data)
        return r

    async def post(self, url, data=None, use_json: bool = True):
        if use_json and data is not None:
            data = json.dumps(data)
        r = await self.request(METH_POST, url, headers=self.__get_headers(), data=data)
        return r

    def __get_headers(self):
        data = {
            "User-Agent": "okhttp/3.7.0",
            "X-App-Version": "3.14.0",
            "X-App-Name": "myAudi",
            "X-Market": "de_DE",
            "Accept": "application/json"
            # "Accept": "application/json, application/vnd.vwg.mbb.vehicleDataDetail_v2_1_0+xml, application/vnd.vwg.mbb.genericError_v1_0_2+xml",
        }
        if self.__token != None:
            data["Authorization"] = "Bearer " + self.__token.get("access_token")

        return data


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
