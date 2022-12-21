import requests
import json
import logging
from datetime import timedelta, datetime

import traceback
import asyncio
import async_timeout

from asyncio import TimeoutError, CancelledError
from aiohttp import ClientSession, ClientResponseError
from aiohttp.hdrs import METH_GET, METH_POST, METH_PUT

from typing import Dict

TIMEOUT = 10

_LOGGER = logging.getLogger(__name__)


class AudiAPI:
    HDR_XAPP_VERSION = "4.13.0"
    HDR_USER_AGENT = "myAudi-Android/4.13.0 (Build 800238275.2210271555) Android/11"

    def __init__(self, session, proxy=None):
        self.__token = None
        self.__xclientid = None
        self._session = session
        if proxy is not None:
            self.__proxy = {"http": proxy, "https": proxy}
        else:
            self.__proxy = None

    def use_token(self, token):
        self.__token = token

    def set_xclient_id(self, xclientid):
        self.__xclientid = xclientid

    async def request(
        self,
        method,
        url,
        data,
        headers: Dict[str, str] = None,
        raw_reply: bool = False,
        raw_contents: bool = False,
        rsp_wtxt: bool = False,
        **kwargs
    ):
        try:
            with async_timeout.timeout(TIMEOUT):
                async with self._session.request(
                    method, url, headers=headers, data=data, **kwargs
                ) as response:
                    if raw_reply:
                        return response
                    if rsp_wtxt:
                        txt = await response.text()
                        return response, txt
                    elif raw_contents:
                        return await response.read()
                    elif response.status == 200 or response.status == 202:
                        return await response.json(loads=json_loads)
                    else:
                        raise ClientResponseError(
                            response.request_info,
                            response.history,
                            status=response.status,
                            message=response.reason,
                        )
        except CancelledError:
            raise TimeoutError("Timeout error")
        except TimeoutError:
            raise TimeoutError("Timeout error")
        except Exception:
            raise

    async def get(
        self, url, raw_reply: bool = False, raw_contents: bool = False, **kwargs
    ):
        full_headers = self.__get_headers()
        r = await self.request(
            METH_GET,
            url,
            data=None,
            headers=full_headers,
            raw_reply=raw_reply,
            raw_contents=raw_contents,
            **kwargs
        )
        return r

    async def put(self, url, data=None, headers: Dict[str, str] = None):
        full_headers = self.__get_headers()
        if headers is not None:
            full_headers.update(headers)
        r = await self.request(METH_PUT, url, headers=full_headers, data=data)
        return r

    async def post(
        self,
        url,
        data=None,
        headers: Dict[str, str] = None,
        use_json: bool = True,
        raw_reply: bool = False,
        raw_contents: bool = False,
        **kwargs
    ):
        full_headers = self.__get_headers()
        if headers is not None:
            full_headers.update(headers)
        if use_json and data is not None:
            data = json.dumps(data)
        r = await self.request(
            METH_POST,
            url,
            headers=full_headers,
            data=data,
            raw_reply=raw_reply,
            raw_contents=raw_contents,
            **kwargs
        )
        return r

    def __get_headers(self):
        data = {
            "Accept": "application/json",
            "Accept-Charset": "utf-8",
            "X-App-Version": self.HDR_XAPP_VERSION,
            "X-App-Name": "myAudi",
            "User-Agent": self.HDR_USER_AGENT,
        }
        if self.__token != None:
            data["Authorization"] = "Bearer " + self.__token.get("access_token")
        if self.__xclientid != None:
            data["X-Client-ID"] = self.__xclientid

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
