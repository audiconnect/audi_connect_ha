import json
import logging
from datetime import datetime

import asyncio

from asyncio import TimeoutError, CancelledError
from aiohttp import ClientResponseError
from aiohttp.hdrs import METH_GET, METH_POST, METH_PUT

from typing import Dict

TIMEOUT = 30

_LOGGER = logging.getLogger(__name__)


class AudiAPI:
    HDR_XAPP_VERSION = "4.31.0"
    HDR_USER_AGENT = "Android/4.31.0 (Build 800341641.root project 'myaudi_android'.ext.buildTime) Android/13"

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
        **kwargs,
    ):
        _LOGGER.debug(
            "Request initiated: method=%s, url=%s, data=%s, headers=%s, kwargs=%s",
            method,
            url,
            data,
            headers,
            kwargs,
        )
        try:
            async with asyncio.timeout(TIMEOUT):
                async with self._session.request(
                    method, url, headers=headers, data=data, **kwargs
                ) as response:
                    # _LOGGER.debug("Response received: status=%s, headers=%s", response.status, response.headers)
                    if raw_reply:
                        # _LOGGER.debug("Returning raw reply")
                        return response
                    if rsp_wtxt:
                        txt = await response.text()
                        # _LOGGER.debug("Returning response text; length=%d", len(txt))
                        return response, txt
                    elif raw_contents:
                        contents = await response.read()
                        # _LOGGER.debug("Returning raw contents; length=%d", len(contents))
                        return contents
                    elif response.status in (200, 202, 207):
                        json_data = await response.json(loads=json_loads)
                        # _LOGGER.debug("Returning JSON data: %s", json_data)
                        return json_data
                    else:
                        # _LOGGER.error("Unexpected response: status=%s, reason=%s", response.status, response.reason)
                        raise ClientResponseError(
                            response.request_info,
                            response.history,
                            status=response.status,
                            message=response.reason,
                        )
        except CancelledError:
            # _LOGGER.error("Request cancelled (Timeout error)")
            raise TimeoutError("Timeout error")
        except TimeoutError:
            # _LOGGER.error("Request timed out")
            raise TimeoutError("Timeout error")
        except Exception:
            # _LOGGER.exception("An unexpected error occurred during request")
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
            **kwargs,
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
        **kwargs,
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
            **kwargs,
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
        if self.__token is not None:
            data["Authorization"] = "Bearer " + self.__token.get("access_token")
        if self.__xclientid is not None:
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
