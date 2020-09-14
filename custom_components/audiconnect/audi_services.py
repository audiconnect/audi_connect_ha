from abc import abstractmethod, ABCMeta
import json

from .audi_models import (
    CurrentVehicleDataResponse,
    VehicleDataResponse,
    VehiclesResponse,
    Vehicle,
)
from .audi_api import AudiAPI
from .util import to_byte_array, get_attr

from hashlib import sha512
import asyncio

from urllib.parse import urlparse, parse_qs

import requests
from bs4 import BeautifulSoup
from requests import RequestException

from typing import Dict


MAX_RESPONSE_ATTEMPTS = 10
REQUEST_STATUS_SLEEP = 10

SUCCEEDED = "succeeded"
FAILED = "failed"
REQUEST_SUCCESSFUL = "request_successful"
REQUEST_FAILED = "request_failed"

CLIENT_ID = "09b6cbec-cd19-4589-82fd-363dfa8c24da@apps_vw-dilab_com"
XCLIENT_ID = "77869e21-e30a-4a92-b016-48ab7d3db1d8"


class BrowserLoginResponse:
    def __init__(self, response: requests.Response, url: str):
        self.response = response  # type: requests.Response
        self.url = url  # type : str

    def get_location(self) -> str:
        """
        Returns the location the previous request redirected to
        """
        location = self.response.headers["Location"]
        if location.startswith("/"):
            # Relative URL
            return BrowserLoginResponse.to_absolute(self.url, location)
        return location

    @classmethod
    def to_absolute(cls, absolute_url, relative_url) -> str:
        """
        Converts a relative url to an absolute url
        :param absolute_url: Absolute url used as baseline
        :param relative_url: Relative url (must start with /)
        :return: New absolute url
        """
        url_parts = urlparse(absolute_url)
        return url_parts.scheme + "://" + url_parts.netloc + relative_url


class AudiService:
    def __init__(self, api: AudiAPI, country: str, spin: str):
        self._api = api
        self._country = country
        self._type = "Audi"
        self._spin = spin

        if self._country is None:
            self._country = "DE"

    async def login(self, user: str, password: str, persist_token: bool = True):
        await self.login_request(user, password)

    async def refresh_vehicle_data(self, vin: str):
        res = await self.request_current_vehicle_data(vin.upper())
        request_id = res.request_id

        checkUrl = "https://msg.volkswagen.de/fs-car/bs/vsr/v1/{type}/{country}/vehicles/{vin}/requests/{requestId}/jobstatus".format(
            type=self._type,
            country=self._country,
            vin=vin.upper(),
            requestId=request_id,
        )

        await self.check_request_succeeded(
            checkUrl,
            "refresh vehicle data",
            REQUEST_SUCCESSFUL,
            REQUEST_FAILED,
            "requestStatusResponse.status",
        )

    async def request_current_vehicle_data(self, vin: str):
        self._api.use_token(self.vwToken)
        data = await self._api.post(
            "https://msg.volkswagen.de/fs-car/bs/vsr/v1/{type}/{country}/vehicles/{vin}/requests".format(
                type=self._type, country=self._country, vin=vin.upper()
            )
        )
        return CurrentVehicleDataResponse(data)

    async def get_stored_vehicle_data(self, vin: str):
        self._api.use_token(self.vwToken)
        data = await self._api.get(
            "https://msg.volkswagen.de/fs-car/bs/vsr/v1/{type}/{country}/vehicles/{vin}/status".format(
                type=self._type, country=self._country, vin=vin.upper()
            )
        )
        return VehicleDataResponse(data)

    async def get_charger(self, vin: str):
        self._api.use_token(self.vwToken)
        return await self._api.get(
            "https://msg.volkswagen.de/fs-car/bs/batterycharge/v1/{type}/{country}/vehicles/{vin}/charger".format(
                type=self._type, country=self._country, vin=vin.upper()
            )
        )

    async def get_climater(self, vin: str):
        self._api.use_token(self.vwToken)
        return await self._api.get(
            "https://msg.volkswagen.de/fs-car/bs/climatisation/v1/{type}/{country}/vehicles/{vin}/climater".format(
                type=self._type, country=self._country, vin=vin.upper()
            )
        )

    async def get_stored_position(self, vin: str):
        self._api.use_token(self.vwToken)
        return await self._api.get(
            "https://msg.volkswagen.de/fs-car/bs/cf/v1/{type}/{country}/vehicles/{vin}/position".format(
                type=self._type, country=self._country, vin=vin.upper()
            )
        )

    async def get_operations_list(self, vin: str):
        self._api.use_token(self.vwToken)
        return await self._api.get(
            "https://mal-1a.prd.ece.vwg-connect.com/api/rolesrights/operationlist/v3/vehicles/"
            + vin.upper()
        )

    async def get_timer(self, vin: str):
        self._api.use_token(self.vwToken)
        return await self._api.get(
            "https://msg.volkswagen.de/fs-car/bs/departuretimer/v1/{type}/{country}/vehicles/{vin}/timer".format(
                type=self._type, country=self._country, vin=vin.upper()
            )
        )

    async def get_vehicles(self):
        self._api.use_token(self.vwToken)
        return await self._api.get(
            "https://msg.volkswagen.de/fs-car/usermanagement/users/v1/{type}/{country}/vehicles".format(
                type=self._type, country=self._country
            )
        )

    async def get_vehicle_information(self):
        self._api.use_token(self.audiToken)
        data = await self._api.get(
            "https://msg.audi.de/myaudi/vehicle-management/v2/vehicles"
        )
        response = VehiclesResponse()
        response.parse(data)
        return response

    async def _get_security_token(self, vin: str, action: str):
        # Challenge
        headers = {
            "User-Agent": "okhttp/3.7.0",
            "X-App-Version": "3.14.0",
            "X-App-Name": "myAudi",
            "Accept": "application/json",
            "Authorization": "Bearer " + self.vwToken.get("access_token"),
        }

        body = await self._api.request(
            "GET",
            "https://mal-1a.prd.ece.vwg-connect.com/api/rolesrights/authorization/v2/vehicles/"
            + vin.upper()
            + "/services/"
            + action
            + "/security-pin-auth-requested",
            headers=headers,
            data=None,
        )
        secToken = body["securityPinAuthInfo"]["securityToken"]
        challenge = body["securityPinAuthInfo"]["securityPinTransmission"]["challenge"]

        # Response
        securityPinHash = self._generate_security_pin_hash(challenge)
        data = {
            "securityPinAuthentication": {
                "securityPin": {
                    "challenge": challenge,
                    "securityPinHash": securityPinHash,
                },
                "securityToken": secToken,
            }
        }

        headers = {
            "User-Agent": "okhttp/3.7.0",
            "Content-Type": "application/json",
            "X-App-Version": "3.14.0",
            "X-App-Name": "myAudi",
            "Accept": "application/json",
            "Authorization": "Bearer " + self.vwToken.get("access_token"),
        }

        body = await self._api.request(
            "POST",
            "https://mal-1a.prd.ece.vwg-connect.com/api/rolesrights/authorization/v2/security-pin-auth-completed",
            headers=headers,
            data=json.dumps(data),
        )
        return body["securityToken"]

    def _get_vehicle_action_header(self, content_type: str, security_token: str):
        headers = {
            "User-Agent": "okhttp/3.7.0",
            "Host": "msg.volkswagen.de",
            "X-App-Version": "3.14.0",
            "X-App-Name": "myAudi",
            "Authorization": "Bearer " + self.vwToken.get("access_token"),
            "Accept-charset": "UTF-8",
            "Content-Type": content_type,
            "Accept": "application/json, application/vnd.vwg.mbb.ChargerAction_v1_0_0+xml,application/vnd.volkswagenag.com-error-v1+xml,application/vnd.vwg.mbb.genericError_v1_0_2+xml, application/vnd.vwg.mbb.RemoteStandheizung_v2_0_0+xml, application/vnd.vwg.mbb.genericError_v1_0_2+xml,application/vnd.vwg.mbb.RemoteLockUnlock_v1_0_0+xml,*/*",
        }

        if security_token != None:
            headers["x-mbbSecToken"] = security_token

        return headers

    async def set_vehicle_lock(self, vin: str, lock: bool):
        security_token = await self._get_security_token(
            vin, "rlu_v1/operations/" + ("LOCK" if lock else "UNLOCK")
        )
        data = '<?xml version="1.0" encoding= "UTF-8" ?><rluAction xmlns="http://audi.de/connect/rlu"><action>{action}</action></rluAction>'.format(
            action="lock" if lock else "unlock"
        )
        headers = self._get_vehicle_action_header(
            "application/vnd.vwg.mbb.RemoteLockUnlock_v1_0_0+xml", security_token
        )
        res = await self._api.request(
            "POST",
            "https://msg.volkswagen.de/fs-car/bs/rlu/v1/{type}/{country}/vehicles/{vin}/actions".format(
                type=self._type, country=self._country, vin=vin.upper()
            ),
            headers=headers,
            data=data,
        )

        checkUrl = "https://msg.volkswagen.de/fs-car/bs/rlu/v1/{type}/{country}/vehicles/{vin}/requests/{requestId}/status".format(
            type=self._type,
            country=self._country,
            vin=vin.upper(),
            requestId=res["rluActionResponse"]["requestId"],
        )

        await self.check_request_succeeded(
            checkUrl,
            "lock vehicle" if lock else "unlock vehicle",
            REQUEST_SUCCESSFUL,
            REQUEST_FAILED,
            "requestStatusResponse.status",
        )

    async def set_battery_charger(self, vin: str, start: bool):
        data = '<?xml version="1.0" encoding= "UTF-8" ?><action><type>{action}</type></action>'.format(
            action="start" if start else "stop"
        )
        headers = self._get_vehicle_action_header(
            "application/vnd.vwg.mbb.ChargerAction_v1_0_0+xml", None
        )
        res = await self._api.request(
            "POST",
            "https://msg.volkswagen.de/fs-car/bs/batterycharge/v1/{type}/{country}/vehicles/{vin}/charger/actions".format(
                type=self._type, country=self._country, vin=vin.upper()
            ),
            headers=headers,
            data=data,
        )

        checkUrl = "https://msg.volkswagen.de/fs-car/bs/batterycharge/v1/{type}/{country}/vehicles/{vin}/charger/actions/{actionid}".format(
            type=self._type,
            country=self._country,
            vin=vin.upper(),
            actionid=res["action"]["actionId"],
        )

        await self.check_request_succeeded(
            checkUrl,
            "start charger" if start else "stop charger",
            SUCCEEDED,
            FAILED,
            "action.actionState",
        )

    async def set_climatisation(self, vin: str, start: bool):
        if start:
            data = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><action><type>startClimatisation</type><settings><heaterSource>electric</heaterSource></settings></action>'
        else:
            data = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><action><type>stopClimatisation</type></action>'

        headers = self._get_vehicle_action_header(
            "application/vnd.vwg.mbb.ClimaterAction_v1_0_0+xml;charset=utf-8", None
        )
        res = await self._api.request(
            "POST",
            "https://msg.volkswagen.de/fs-car/bs/climatisation/v1/{type}/{country}/vehicles/{vin}/climater/actions".format(
                type=self._type, country=self._country, vin=vin.upper()
            ),
            headers=headers,
            data=data,
        )

        checkUrl = "https://msg.volkswagen.de/fs-car/bs/climatisation/v1/{type}/{country}/vehicles/{vin}/climater/actions/{actionid}".format(
            type=self._type,
            country=self._country,
            vin=vin.upper(),
            actionid=res["action"]["actionId"],
        )

        await self.check_request_succeeded(
            checkUrl,
            "start climatisation" if start else "stop climatisation",
            SUCCEEDED,
            FAILED,
            "action.actionState",
        )

    async def set_window_heating(self, vin: str, start: bool):
        data = '<?xml version="1.0" encoding= "UTF-8" ?><action><type>{action}</type></action>'.format(
            action="startWindowHeating" if start else "stopWindowHeating"
        )

        headers = self._get_vehicle_action_header(
            "application/vnd.vwg.mbb.ClimaterAction_v1_0_0+xml", None
        )
        res = await self._api.request(
            "POST",
            "https://msg.volkswagen.de/fs-car/bs/climatisation/v1/{type}/{country}/vehicles/{vin}/climater/actions".format(
                type=self._type, country=self._country, vin=vin.upper()
            ),
            headers=headers,
            data=data,
        )

        checkUrl = "https://msg.volkswagen.de/fs-car/bs/climatisation/v1/{type}/{country}/vehicles/{vin}/climater/actions/{actionid}".format(
            type=self._type,
            country=self._country,
            vin=vin.upper(),
            actionid=res["action"]["actionId"],
        )

        await self.check_request_succeeded(
            checkUrl,
            "start window heating" if start else "stop window heating",
            SUCCEEDED,
            FAILED,
            "action.actionState",
        )

    async def set_pre_heater(self, vin: str, activate: bool):
        security_token = await self._get_security_token(
            vin, "rheating_v1/operations/P_QSACT"
        )

        data = '<?xml version="1.0" encoding= "UTF-8" ?>{input}'.format(
            input='<performAction xmlns="http://audi.de/connect/rs"><quickstart><active>true</active></quickstart></performAction>'
            if activate
            else '<performAction xmlns="http://audi.de/connect/rs"><quickstop><active>false</active></quickstop></performAction>'
        )

        headers = self._get_vehicle_action_header(
            "application/vnd.vwg.mbb.RemoteStandheizung_v2_0_0+xml", security_token
        )
        await self._api.request(
            "POST",
            "https://msg.volkswagen.de/fs-car/bs/rs/v1/{type}/{country}/vehicles/{vin}/action".format(
                type=self._type, country=self._country, vin=vin.upper()
            ),
            headers=headers,
            data=data,
        )

    async def check_request_succeeded(
        self, url: str, action: str, successCode: str, failedCode: str, path: str
    ):

        for _ in range(MAX_RESPONSE_ATTEMPTS):
            await asyncio.sleep(REQUEST_STATUS_SLEEP)

            self._api.use_token(self.vwToken)
            res = await self._api.get(url)

            status = get_attr(res, path)

            if status is None or (failedCode is not None and status == failedCode):
                raise Exception(
                    "Cannot {action}, return code '{code}'".format(
                        action=action, code=status
                    )
                )

            if status == successCode:
                return

        raise Exception("Cannot {action}, operation timed out".format(action=action))

    # 13.09.2020 New login taken from https://github.com/davidgiga1993/AudiAPI/issues/13
    async def login_request(self, user: str, password: str):
        self._api.use_token(None)

        # OpenID Configuration
        openIdConfig = await self._api.get(
            "https://app-api.live-my.audi.com/myaudiappidk/v1/openid-configuration"
        )
        authorization_endpoint = openIdConfig.get("authorization_endpoint")

        # Authorization code
        query_params = {
            "response_type": "code",
            "client_id": CLIENT_ID,
            "redirect_uri": "myaudi:///",
            "scope": "address profile badge birthdate birthplace nationalIdentifier nationality profession email "
            "vin phone nickname name picture mbb gallery openid",
            "state": "7f8260b5-682f-4db8-b171-50a5189a1c08",
            "nonce": "583b9af2-7799-4c72-9cb0-e6c0f42b87b3",
            "prompt": "login",
            "ui_locales": "en-US en",
        }

        reply = await self._api.get(
            authorization_endpoint,
            raw_reply=True,
            allow_redirects=False,
            params=query_params,
        )

        # Submit the email
        reply = await self._emulate_browser(
            BrowserLoginResponse(reply, authorization_endpoint), {"email": user}
        )
        # Submit the password
        reply = await self._emulate_browser(reply, {"password": password})

        sso_url = reply.get_location()
        sso_reply = await self._api.get(sso_url, raw_reply=True, allow_redirects=False)

        consent_url = BrowserLoginResponse(sso_reply, sso_url).get_location()
        consent_reply = await self._api.get(
            consent_url, raw_reply=True, allow_redirects=False
        )

        success_url = BrowserLoginResponse(consent_reply, consent_url).get_location()
        success_reply = await self._api.get(
            success_url, raw_reply=True, allow_redirects=False
        )

        my_audi_callback_url = success_reply.headers.get("location")
        query_strings = parse_qs(urlparse(my_audi_callback_url).query)
        login_code = query_strings["code"][0]

        # Get Token
        data = {
            "client_id": CLIENT_ID,
            "grant_type": "authorization_code",
            "response_type": "token id_token",
            "code": login_code,
            "redirect_uri": "myaudi:///",
        }
        reply = await self._api.post(
            "https://app-api.my.audi.com/myaudiappidk/v1/token",
            data=data,
            use_json=False,
        )
        app_idk_token = reply

        # Get the Audi Token
        data = {
            "config": "myaudi",
            "grant_type": "id_token",
            "stage": "live",
            "token": app_idk_token.get("access_token"),
        }
        reply = await self._api.post(
            "https://app-api.live-my.audi.com/azs/v1/token", data=data
        )
        self.audiToken = reply

        # Get the VW Token
        data = {
            "grant_type": "id_token",
            "scope": "sc2:fal",
            "token": app_idk_token.get("id_token"),
        }
        headers = {"X-Client-ID": XCLIENT_ID}
        reply = await self._api.post(
            "https://mbboauth-1d.prd.ece.vwg-connect.com/mbbcoauth/mobile/oauth2/v1/token",
            data=data,
            headers=headers,
            use_json=False,
        )
        self.vwToken = reply

    def _generate_security_pin_hash(self, challenge):
        pin = to_byte_array(self._spin)
        byteChallenge = to_byte_array(challenge)
        b = bytes(pin + byteChallenge)
        return sha512(b).hexdigest().upper()

    async def _emulate_browser(
        self, reply: BrowserLoginResponse, form_data: Dict[str, str]
    ) -> BrowserLoginResponse:
        # The reply redirects to the login page
        login_location = reply.get_location()
        page_reply = await self._api.get(login_location, raw_contents=True)

        # Now parse the html body and extract the target url, csfr token and other required parameters
        html = BeautifulSoup(page_reply, "html.parser")
        form_tag = html.find("form")

        form_inputs = html.find_all("input", attrs={"type": "hidden"})
        for form_input in form_inputs:
            name = form_input.get("name")
            form_data[name] = form_input.get("value")

        # Extract the target url
        action = form_tag.get("action")
        if action.startswith("http"):
            # Absolute url
            username_post_url = action
        elif action.startswith("/"):
            # Relative to domain
            username_post_url = BrowserLoginResponse.to_absolute(login_location, action)
        else:
            raise RequestException("Unknown form action: " + action)

        headers = {"referer": login_location}
        reply = await self._api.post(
            username_post_url,
            form_data,
            headers=headers,
            use_json=False,
            raw_reply=True,
            allow_redirects=False,
        )
        return BrowserLoginResponse(reply, username_post_url)
