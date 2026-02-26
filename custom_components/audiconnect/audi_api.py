import json
import logging
from datetime import datetime
import asyncio
from asyncio import TimeoutError, CancelledError
from aiohttp import ClientResponseError
from aiohttp.hdrs import METH_GET, METH_POST, METH_PUT
from typing import Dict

# ===========================================
# VERBOSE DEBUG TOGGLE
# Set to True to log EVERYTHING (full headers, full body, raw JSON, etc.)
# Set to False for normal operation (minimal debug output)
DEBUG_VERBOSE = False
# ===========================================

TIMEOUT = 30
_LOGGER = logging.getLogger(__name__)


class AudiAPI:
    HDR_XAPP_VERSION = "4.31.0"
    HDR_USER_AGENT = "Android/4.31.0 (Build 800341641.root project 'myaudi_android'.ext.buildTime) Android/13"

    def __init__(self, session, proxy=None):
        self.__token = None
        self.__xclientid = None
        self._session = session
        self.__proxy = {"http": proxy, "https": proxy} if proxy else None

    def use_token(self, token):
        self.__token = token
        if DEBUG_VERBOSE:
            _LOGGER.debug("[use_token] Token set: %s", token)

    def set_xclient_id(self, xclientid):
        self.__xclientid = xclientid
        if DEBUG_VERBOSE:
            _LOGGER.debug("[set_xclient_id] X-Client-ID set: %s", xclientid)

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
        if DEBUG_VERBOSE:
            _LOGGER.debug("[REQUEST INITIATED]")
            _LOGGER.debug("Method: %s", method)
            _LOGGER.debug("URL: %s", url)
            _LOGGER.debug("Data: %s", data)
            _LOGGER.debug("Headers: %s", headers)
            _LOGGER.debug("Kwargs: %s", kwargs)
            _LOGGER.debug("Proxy: %s", self.__proxy)

        try:
            async with asyncio.timeout(TIMEOUT):
                async with self._session.request(
                    method, url, headers=headers, data=data, **kwargs
                ) as response:
                    if DEBUG_VERBOSE:
                        _LOGGER.debug("[RESPONSE RECEIVED]")
                        _LOGGER.debug("Status: %s", response.status)
                        _LOGGER.debug("Reason: %s", response.reason)
                        _LOGGER.debug("Headers: %s", dict(response.headers))

                    if raw_reply:
                        if DEBUG_VERBOSE:
                            _LOGGER.debug("Returning raw reply object.")
                        return response

                    if rsp_wtxt:
                        txt = await response.text()
                        if DEBUG_VERBOSE:
                            _LOGGER.debug("Response text (full): %s", txt)
                        else:
                            _LOGGER.debug(
                                "Returning response text; length=%d", len(txt)
                            )
                        return response, txt

                    elif raw_contents:
                        contents = await response.read()
                        if DEBUG_VERBOSE:
                            _LOGGER.debug("Raw contents (bytes): %s", contents)
                        else:
                            _LOGGER.debug(
                                "Returning raw contents; length=%d", len(contents)
                            )
                        return contents

                    elif response.status in (200, 202, 207):
                        raw_body = await response.text()
                        if DEBUG_VERBOSE:
                            _LOGGER.debug(
                                "Raw JSON text (before parsing): %s", raw_body
                            )
                        json_data = json_loads(raw_body)
                        if DEBUG_VERBOSE:
                            _LOGGER.debug("Parsed JSON data (full): %s", json_data)
                        else:
                            _LOGGER.debug("Returning JSON data: %s", json_data)
                        return json_data

                    else:
                        # this should be refactored:
                        # 204 is a valid response for some requests (e.g. update_vehicle_position)
                        # and should not raise an error.
                        # request should return a tuple indicating the response itself and the
                        # http-status
                        if response.status != 204:
                            _LOGGER.debug(
                                "Non-success response: status=%s, reason=%s — will be handled by caller",
                                response.status,
                                response.reason,
                            )
                            if DEBUG_VERBOSE:
                                _LOGGER.debug(
                                    "Response url: %s, body: %s",
                                    url,
                                    await response.text(),
                                )
                        raise ClientResponseError(
                            response.request_info,
                            response.history,
                            status=response.status,
                            message=response.reason,
                        )

        except CancelledError:
            if DEBUG_VERBOSE:
                _LOGGER.debug("Request cancelled (CancelledError).")
            raise TimeoutError("Timeout error")

        except TimeoutError:
            if DEBUG_VERBOSE:
                _LOGGER.debug("Request timed out after %s seconds.", TIMEOUT)
            raise TimeoutError("Timeout error")

        except Exception as e:
            if DEBUG_VERBOSE:
                _LOGGER.exception("Unexpected exception during request: %s", e)
            raise

    async def get(
        self, url, raw_reply: bool = False, raw_contents: bool = False, **kwargs
    ):
        full_headers = self.__get_headers()
        if DEBUG_VERBOSE:
            _LOGGER.debug("[GET] URL: %s | Headers: %s", url, full_headers)
        return await self.request(
            METH_GET,
            url,
            data=None,
            headers=full_headers,
            raw_reply=raw_reply,
            raw_contents=raw_contents,
            **kwargs,
        )

    async def put(self, url, data=None, headers: Dict[str, str] = None):
        full_headers = self.__get_headers()
        if headers:
            full_headers.update(headers)
        if DEBUG_VERBOSE:
            _LOGGER.debug(
                "[PUT] URL: %s | Data: %s | Headers: %s", url, data, full_headers
            )
        return await self.request(METH_PUT, url, headers=full_headers, data=data)

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
        if headers:
            full_headers.update(headers)
        if use_json and data is not None:
            data = json.dumps(data)
        if DEBUG_VERBOSE:
            _LOGGER.debug(
                "[POST] URL: %s | Data: %s | Headers: %s", url, data, full_headers
            )
        return await self.request(
            METH_POST,
            url,
            headers=full_headers,
            data=data,
            raw_reply=raw_reply,
            raw_contents=raw_contents,
            **kwargs,
        )

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
        if DEBUG_VERBOSE:
            _LOGGER.debug("[HEADERS BUILT]: %s", data)
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
