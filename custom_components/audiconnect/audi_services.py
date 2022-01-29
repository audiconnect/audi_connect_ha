from abc import abstractmethod, ABCMeta
import json
import uuid
import base64
import os
import math
import re
import logging
from time import strftime, gmtime
from datetime import datetime

from .audi_models import (
    CurrentVehicleDataResponse,
    VehicleDataResponse,
    VehiclesResponse,
    Vehicle,
)
from .audi_api import AudiAPI
from .util import to_byte_array, get_attr

from hashlib import sha256, sha512
import hmac
import asyncio

from urllib.parse import urlparse, parse_qs, urlencode

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

XCLIENT_ID = "77869e21-e30a-4a92-b016-48ab7d3db1d8"

_LOGGER = logging.getLogger(__name__)


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
        self._language = None
        self._type = "Audi"
        self._spin = spin
        self._homeRegion = {}
        self._homeRegionSetter = {}
        self.mbbOAuthBaseURL = None
        self.mbboauthToken = None
        self.xclientId = None

        if self._country is None:
            self._country = "DE"

    def get_hidden_html_input_form_data(self, response, form_data: Dict[str, str]):
        # Now parse the html body and extract the target url, csfr token and other required parameters
        html = BeautifulSoup(response, "html.parser")
        form_tag = html.find("form")

        form_inputs = html.find_all("input", attrs={"type": "hidden"})
        for form_input in form_inputs:
            name = form_input.get("name")
            form_data[name] = form_input.get("value")

        return form_data

    def get_post_url(self, response, url):
        # Now parse the html body and extract the target url, csfr token and other required parameters
        html = BeautifulSoup(response, "html.parser")
        form_tag = html.find("form")

        # Extract the target url
        action = form_tag.get("action")
        if action.startswith("http"):
            # Absolute url
            username_post_url = action
        elif action.startswith("/"):
            # Relative to domain
            username_post_url = BrowserLoginResponse.to_absolute(url, action)
        else:
            raise RequestException("Unknown form action: " + action)
        return username_post_url

    async def login(self, user: str, password: str, persist_token: bool = True):
        await self.login_request(user, password)

    async def refresh_vehicle_data(self, vin: str):
        res = await self.request_current_vehicle_data(vin.upper())
        request_id = res.request_id

        checkUrl = "{homeRegion}/fs-car/bs/vsr/v1/{type}/{country}/vehicles/{vin}/requests/{requestId}/jobstatus".format(
            homeRegion=await self._get_home_region(vin.upper()),
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
            "{homeRegion}/fs-car/bs/vsr/v1/{type}/{country}/vehicles/{vin}/requests".format(
                homeRegion=await self._get_home_region(vin.upper()),
                type=self._type, country=self._country, vin=vin.upper()
            )
        )
        return CurrentVehicleDataResponse(data)

    async def get_preheater(self, vin: str):
        self._api.use_token(self.vwToken)
        return await self._api.get(
            "{homeRegion}/fs-car/bs/rs/v1/{type}/{country}/vehicles/{vin}/status".format(
                homeRegion=await self._get_home_region(vin.upper()),
                type=self._type, country=self._country, vin=vin.upper()
            )
        )

    async def get_preheater(self, vin: str):
        self._api.use_token(self.vwToken)
        return await self._api.get(
            "{homeRegion}/fs-car/bs/rs/v1/{type}/{country}/vehicles/{vin}/status".format(
                homeRegion=await self._get_home_region(vin.upper()),
                type=self._type, country=self._country, vin=vin.upper()
            )
        )

    async def get_stored_vehicle_data(self, vin: str):
        self._api.use_token(self.vwToken)
        data = await self._api.get(
            "{homeRegion}/fs-car/bs/vsr/v1/{type}/{country}/vehicles/{vin}/status".format(
                homeRegion=await self._get_home_region(vin.upper()),
                type=self._type, country=self._country, vin=vin.upper()
            )
        )
        return VehicleDataResponse(data)

    async def get_charger(self, vin: str):
        self._api.use_token(self.vwToken)
        return await self._api.get(
            "{homeRegion}/fs-car/bs/batterycharge/v1/{type}/{country}/vehicles/{vin}/charger".format(
                homeRegion=await self._get_home_region(vin.upper()),
                type=self._type, country=self._country, vin=vin.upper()
            )
        )

    async def get_climater(self, vin: str):
        self._api.use_token(self.vwToken)
        return await self._api.get(
            "{homeRegion}/fs-car/bs/climatisation/v1/{type}/{country}/vehicles/{vin}/climater".format(
                homeRegion=await self._get_home_region(vin.upper()),
                type=self._type, country=self._country, vin=vin.upper()
            )
        )

    async def get_stored_position(self, vin: str):
        self._api.use_token(self.vwToken)
        return await self._api.get(
            "{homeRegion}/fs-car/bs/cf/v1/{type}/{country}/vehicles/{vin}/position".format(
                homeRegion=await self._get_home_region(vin.upper()),
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
            "{homeRegion}/fs-car/bs/departuretimer/v1/{type}/{country}/vehicles/{vin}/timer".format(
                homeRegion=await self._get_home_region(vin.upper()),
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
        headers = {
            "Accept": "application/json",
            "Accept-Charset": "utf-8",
            "X-App-Name": "myAudi",
            "X-App-Version": "4.5.0",
            "Accept-Language": "{l}-{c}".format(
                l=self._language, c=self._country.upper()
            ),
            "X-User-Country": self._country.upper(),
            "User-Agent": "myAudi-Android/4.5.0(Build800236547.2110181440)Android/11",
            "Authorization": "Bearer " + self.audiToken["access_token"],
            "Content-Type": "application/json; charset=utf-8",
        }
        req_data = {
            "query": "query vehicleList {\n userVehicles {\n vin\n mappingVin\n vehicle { core { modelYear\n }\n media { shortName\n longName }\n }\n csid\n commissionNumber\n type\n devicePlatform\n mbbConnect\n userRole {\n role\n }\n vehicle {\n classification {\n driveTrain\n }\n }\n nickname\n }\n}"
        }
        req_rsp, rep_rsptxt = await self._api.request(
            "POST",
            "https://app-api.live-my.audi.com/vgql/v1/graphql",
            json.dumps(req_data),
            headers=headers,
            allow_redirects=False,
            rsp_wtxt = True,
        )
        vins = json.loads(rep_rsptxt)
        if "data" not in vins:
            raise Exception("Invalid json in get_vehicle_information")

        response = VehiclesResponse()
        response.parse(vins["data"])
        return response

    async def get_vehicle_data(self, vin: str):
        self._api.use_token(self.vwToken)
        data = await self._api.get(
            "{homeRegion}/fs-car/vehicleMgmt/vehicledata/v2/{type}/{country}/vehicles/{vin}/".format(
                homeRegion=await self._get_home_region(vin.upper()),
                type=self._type, country=self._country, vin=vin.upper()
            )
        )

    async def _fill_home_region(self, vin: str):
        self._homeRegion[vin] = "https://msg.volkswagen.de"
        self._homeRegionSetter[vin] = "https://mal-1a.prd.ece.vwg-connect.com"

        try:
            self._api.use_token(self.vwToken)
            res = await self._api.get("https://mal-1a.prd.ece.vwg-connect.com/api/cs/vds/v1/vehicles/{vin}/homeRegion".format(vin=vin))
            if res != None and res.get("homeRegion") != None and res["homeRegion"].get("baseUri") != None and res["homeRegion"]["baseUri"].get("content") != None:
                uri = res["homeRegion"]["baseUri"]["content"]
                if uri != "https://mal-1a.prd.ece.vwg-connect.com/api":
                    self._homeRegionSetter[vin] = uri.split("/api")[0]
                    self._homeRegion[vin] = self._homeRegionSetter[vin].replace("mal-", "fal-")
        except Exception:
            pass

    async def _get_home_region(self, vin: str):
        if self._homeRegion.get(vin) != None:
            return self._homeRegion[vin]

        await self._fill_home_region(vin)

        return self._homeRegion[vin]

    async def _get_home_region_setter(self, vin: str):
        if self._homeRegionSetter.get(vin) != None:
            return self._homeRegionSetter[vin]

        await self._fill_home_region(vin)

        return self._homeRegionSetter[vin]

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
            "{homeRegionSetter}/api/rolesrights/authorization/v2/vehicles/".format(homeRegionSetter=await self._get_home_region_setter(vin.upper()))
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
            "{homeRegionSetter}/api/rolesrights/authorization/v2/security-pin-auth-completed".format(homeRegionSetter=await self._get_home_region_setter(vin.upper())),
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
            "{homeRegion}/fs-car/bs/rlu/v1/{type}/{country}/vehicles/{vin}/actions".format(
                homeRegion=await self._get_home_region(vin.upper()),
                type=self._type, country=self._country, vin=vin.upper()
            ),
            headers=headers,
            data=data,
        )

        checkUrl = "{homeRegion}/fs-car/bs/rlu/v1/{type}/{country}/vehicles/{vin}/requests/{requestId}/status".format(
            homeRegion=await self._get_home_region(vin.upper()),
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
            "{homeRegion}/fs-car/bs/batterycharge/v1/{type}/{country}/vehicles/{vin}/charger/actions".format(
                homeRegion=await self._get_home_region(vin.upper()),
                type=self._type, country=self._country, vin=vin.upper()
            ),
            headers=headers,
            data=data,
        )

        checkUrl = "{homeRegion}/fs-car/bs/batterycharge/v1/{type}/{country}/vehicles/{vin}/charger/actions/{actionid}".format(
            homeRegion=await self._get_home_region(vin.upper()),
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
            "{homeRegion}/fs-car/bs/climatisation/v1/{type}/{country}/vehicles/{vin}/climater/actions".format(
                homeRegion=await self._get_home_region(vin.upper()),
                type=self._type, country=self._country, vin=vin.upper()
            ),
            headers=headers,
            data=data,
        )

        checkUrl = "{homeRegion}/fs-car/bs/climatisation/v1/{type}/{country}/vehicles/{vin}/climater/actions/{actionid}".format(
            homeRegion=await self._get_home_region(vin.upper()),
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
            "{homeRegion}/fs-car/bs/climatisation/v1/{type}/{country}/vehicles/{vin}/climater/actions".format(
                homeRegion=await self._get_home_region(vin.upper()),
                type=self._type, country=self._country, vin=vin.upper()
            ),
            headers=headers,
            data=data,
        )

        checkUrl = "{homeRegion}/fs-car/bs/climatisation/v1/{type}/{country}/vehicles/{vin}/climater/actions/{actionid}".format(
            homeRegion=await self._get_home_region(vin.upper()),
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
            "{homeRegion}/fs-car/bs/rs/v1/{type}/{country}/vehicles/{vin}/action".format(
                homeRegion=await self._get_home_region(vin.upper()),
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

    # TR/2021-12-01: Refresh token before it expires
    # returns True when refresh was required and succesful, otherwise False
    async def refresh_token_if_necessary(self, elapsed_sec: int) -> bool:
        if self.mbboauthToken is None:
            return False
        if "refresh_token" not in self.mbboauthToken:
            return False
        if "expires_in" not in self.mbboauthToken:
            return False

        if (elapsed_sec * 2) < self.mbboauthToken["expires_in"]:
            # refresh not needed now
            return False

        try:
            headers = {
                "Accept": "application/json",
                "Accept-Charset": "utf-8",
                "User-Agent": "myAudi-Android/4.5.0(Build800236547.2110181440)Android/11",
                "Content-Type": "application/x-www-form-urlencoded",
                "X-Client-ID": self.xclientId,
            }
            mbboauth_refresh_data = {
                "grant_type": "refresh_token",
                "token": self.mbboauthToken["refresh_token"],
                "scope": "sc2:fal",
                # "vin": vin,  << App uses a dedicated VIN here, but it works without, don't know
            }
            encoded_mbboauth_refresh_data = urlencode(mbboauth_refresh_data, encoding="utf-8").replace("+", "%20")
            mbboauth_refresh_rsp, mbboauth_refresh_rsptxt = await self._api.request(
                "POST",
                self.mbbOAuthBaseURL + "/mobile/oauth2/v1/token",
                encoded_mbboauth_refresh_data,
                headers=headers,
                allow_redirects=False,
                rsp_wtxt = True,
            )
            # this code is the old "vwToken"
            self.vwToken = json.loads(mbboauth_refresh_rsptxt)
            return True

        except Exception as exception:
            _LOGGER.error("Refresh token failed: " + str(exception))
            return False

    # TR/2021-12-01 updated to match behaviour of Android myAudi 4.5.0
    async def login_request(self, user: str, password: str):
        self._api.use_token(None)
        self._api.set_xclient_id(None)
        self.xclientId = None

        # get markets
        markets_json = await self._api.request(
            "GET",
            "https://content.app.my.audi.com/service/mobileapp/configurations/markets",
            None,
        )
        if (
            self._country.upper()
            not in markets_json["countries"]["countrySpecifications"]
        ):
            raise Exception("Country not found")
        self._language = markets_json["countries"]["countrySpecifications"][
            self._country.upper()
        ]["defaultLanguage"]

        # Dynamic configuration URLs
        marketcfg_url = "https://content.app.my.audi.com/service/mobileapp/configurations/market/{c}/{l}?v=4.5.1".format(
            c=self._country, l=self._language
        )
        openidcfg_url = "https://idkproxy-service.apps.{0}.vwapps.io/v1/{0}/openid-configuration".format(
           "na" if self._country.upper() == "US" else "emea")

        # get market config
        marketcfg_json = await self._api.request("GET", marketcfg_url, None)

        # use dynamic config from marketcfg
        client_id = "09b6cbec-cd19-4589-82fd-363dfa8c24da@apps_vw-dilab_com"
        if "idkClientIDAndroidLive" in marketcfg_json:
            client_id = marketcfg_json["idkClientIDAndroidLive"]

        authorizationServerBaseURLLive = "https://aazsproxy-service.apps.emea.vwapps.io"
        if "authorizationServerBaseURLLive" in marketcfg_json:
            authorizationServerBaseURLLive = marketcfg_json[
                "authorizationServerBaseURLLive"
            ]
        self.mbbOAuthBaseURL = "https://mbboauth-1d.prd.ece.vwg-connect.com/mbbcoauth"
        if "mbbOAuthBaseURLLive" in marketcfg_json:
            self.mbbOAuthBaseURL = marketcfg_json["mbbOAuthBaseURLLive"]

        # get openId config
        openidcfg_json = await self._api.request("GET", openidcfg_url, None)

        # use dynamic config from openId config
        authorization_endpoint = "https://identity.vwgroup.io/oidc/v1/authorize"
        if "authorization_endpoint" in openidcfg_json:
            authorization_endpoint = openidcfg_json["authorization_endpoint"]
        token_endpoint = "https://idkproxy-service.apps.emea.vwapps.io/v1/emea/token"
        if "token_endpoint" in openidcfg_json:
            token_endpoint = openidcfg_json["token_endpoint"]
        revocation_endpoint = (
            "https://idkproxy-service.apps.emea.vwapps.io/v1/emea/revoke"
        )
        if revocation_endpoint in openidcfg_json:
            revocation_endpoint = openidcfg_json["revocation_endpoint"]

        # generate code_challenge
        code_verifier = str(base64.urlsafe_b64encode(os.urandom(32)), "utf-8").strip(
            "="
        )
        code_challenge = str(
            base64.urlsafe_b64encode(
                sha256(code_verifier.encode("ascii", "ignore")).digest()
            ),
            "utf-8",
        ).strip("=")
        code_challenge_method = "S256"

        #
        state = str(uuid.uuid4())
        nonce = str(uuid.uuid4())

        # login page
        headers = {
            "Accept": "application/json",
            "Accept-Charset": "utf-8",
            "X-App-Version": "4.5.0",
            "X-App-Name": "myAudi",
            "User-Agent": "myAudi-Android/4.5.0(Build800236547.2110181440)Android/11",
        }
        idk_data = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": "myaudi:///",
            "scope": "address profile badge birthdate birthplace nationalIdentifier nationality profession email vin phone nickname name picture mbb gallery openid",
            "state": state,
            "nonce": nonce,
            "prompt": "login",
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
            "ui_locales": "de-de de",
        }
        idk_rsp, idk_rsptxt = await self._api.request(
            "GET",
            authorization_endpoint,
            None,
            headers=headers,
            params=idk_data,
            rsp_wtxt = True,
        )

        # form_data with email
        submit_data = self.get_hidden_html_input_form_data(idk_rsptxt, {"email": user})
        submit_url = self.get_post_url(idk_rsptxt, authorization_endpoint)
        # send email
        email_rsp, email_rsptxt = await self._api.request(
            "POST",
            submit_url,
            submit_data,
            headers=headers,
            cookies=idk_rsp.cookies,
            allow_redirects=True,
            rsp_wtxt = True,
        )

        # form_data with password
        # 2022-01-29: new HTML response uses a js two build the html form data + button.
        #             Therefore it's not possible to extract hmac and other form data. 
        #             --> extract hmac from embedded js snippet.
        regex_res = re.findall("\"hmac\"\s*:\s*\"[0-9a-fA-F]+\"", email_rsptxt)
        if regex_res:
           submit_url = submit_url.replace("identifier", "authenticate")
           submit_data["hmac"] = regex_res[0].split(":")[1].strip('"')
           submit_data["password"] = password
        else:
           submit_data = self.get_hidden_html_input_form_data(email_rsptxt, {"password": password})
           submit_url = self.get_post_url(email_rsptxt, submit_url)

        # send password
        pw_rsp, pw_rsptxt = await self._api.request(
            "POST",
            submit_url,
            submit_data,
            headers=headers,
            cookies=idk_rsp.cookies,
            allow_redirects=False,
            rsp_wtxt = True,
        )

        # forward1 after pwd
        fwd1_rsp, fwd1_rsptxt = await self._api.request(
            "GET",
            pw_rsp.headers["Location"],
            None,
            headers=headers,
            cookies=idk_rsp.cookies,
            allow_redirects=False,
            rsp_wtxt = True,
        )
        # forward2 after pwd
        fwd2_rsp, fwd2_rsptxt = await self._api.request(
            "GET",
            fwd1_rsp.headers["Location"],
            None,
            headers=headers,
            cookies=idk_rsp.cookies,
            allow_redirects=False,
            rsp_wtxt = True,
        )
        # get tokens
        codeauth_rsp, codeauth_rsptxt = await self._api.request(
            "GET",
            fwd2_rsp.headers["Location"],
            None,
            headers=headers,
            cookies=fwd2_rsp.cookies,
            allow_redirects=False,
            rsp_wtxt = True,
        )
        authcode_parsed = urlparse(
            codeauth_rsp.headers["Location"][len("myaudi:///?") :]
        )
        authcode_strings = parse_qs(authcode_parsed.path)

        # Calcualte X-QMAuth value
        gmtime_100sec = int(
            (datetime.utcnow() - datetime(1970, 1, 1)).total_seconds() / 100
        )
        xqmauth_secret = bytes([95,14,23,256-99,256-87,17,0,256-106,256-114,19,256-109,94,256-38,106,43,94,58,256-46,77,39,17,29,87,11,256-89,256-76,256-127,256-55,26,256-18,127,256-81])
        xqmauth_val = hmac.new(
            xqmauth_secret,
            str(gmtime_100sec).encode("ascii", "ignore"),
            digestmod="sha256",
        ).hexdigest()
        X_QMAuth = "v1:e94ffc03:" + xqmauth_val
        # hdr
        headers = {
            "Accept": "application/json",
            "Accept-Charset": "utf-8",
            "X-QMAuth": X_QMAuth,
            "User-Agent": "myAudi-Android/4.5.0(Build800236547.2110181440)Android/11",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        # IDK token request data
        tokenreq_data = {
            "client_id": client_id,
            "grant_type": "authorization_code",
            "code": authcode_strings["code"][0],
            "redirect_uri": "myaudi:///",
            "response_type": "token id_token",
            "code_verifier": code_verifier,
        }
        # IDK token request
        encoded_tokenreq_data = urlencode(tokenreq_data, encoding="utf-8").replace("+","%20")
        bearer_token_rsp, bearer_token_rsptxt = await self._api.request(
            "POST",
            token_endpoint,
            encoded_tokenreq_data,
            headers=headers,
            allow_redirects=False,
            rsp_wtxt = True,
        )
        bearer_token_json = json.loads(bearer_token_rsptxt)

        # AZS token
        headers = {
            "Accept": "application/json",
            "Accept-Charset": "utf-8",
            "X-App-Version": "4.5.0",
            "X-App-Name": "myAudi",
            "User-Agent": "myAudi-Android/4.5.0(Build800236547.2110181440)Android/11",
            "Content-Type": "application/json; charset=utf-8",
        }
        asz_req_data = {
            "token": bearer_token_json["access_token"],
            "grant_type": "id_token",
            "stage": "live",
            "config": "myaudi",
        }
        azs_token_rsp, azs_token_rsptxt = await self._api.request(
            "POST",
            authorizationServerBaseURLLive + "/token",
            json.dumps(asz_req_data),
            headers=headers,
            allow_redirects=False,
            rsp_wtxt = True,
        )
        azs_token_json = json.loads(azs_token_rsptxt)
        self.audiToken = azs_token_json

        # mbboauth client register
        headers = {
            "Accept": "application/json",
            "Accept-Charset": "utf-8",
            "User-Agent": "myAudi-Android/4.5.0(Build800236547.2110181440)Android/11",
            "Content-Type": "application/json; charset=utf-8",
        }
        mbboauth_reg_data = {
            "client_name": "SM-A405FN",
            "platform": "google",
            "client_brand": "Audi",
            "appName": "myAudi",
            "appVersion": "4.5.0",
            "appId": "de.myaudi.mobile.assistant",
        }
        mbboauth_client_reg_rsp, mbboauth_client_reg_rsptxt = await self._api.request(
            "POST",
            self.mbbOAuthBaseURL + "/mobile/register/v1",
            json.dumps(mbboauth_reg_data),
            headers=headers,
            allow_redirects=False,
            rsp_wtxt = True,
        )
        mbboauth_client_reg_json = json.loads(mbboauth_client_reg_rsptxt)
        self.xclientId = mbboauth_client_reg_json["client_id"]
        self._api.set_xclient_id(self.xclientId)

        # mbboauth auth
        headers = {
            "Accept": "application/json",
            "Accept-Charset": "utf-8",
            "User-Agent": "myAudi-Android/4.5.0(Build800236547.2110181440)Android/11",
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Client-ID": self.xclientId,
        }
        mbboauth_auth_data = {
            "grant_type": "id_token",
            "token": bearer_token_json["id_token"],
            "scope": "sc2:fal",
        }
        encoded_mbboauth_auth_data = urlencode(mbboauth_auth_data, encoding="utf-8").replace("+","%20")
        mbboauth_auth_rsp, mbboauth_auth_rsptxt = await self._api.request(
            "POST",
            self.mbbOAuthBaseURL + "/mobile/oauth2/v1/token",
            encoded_mbboauth_auth_data,
            headers=headers,
            allow_redirects=False,
            rsp_wtxt = True,
        )
        mbboauth_auth_json = json.loads(mbboauth_auth_rsptxt)
        # store token and expiration time
        self.mbboauthToken = mbboauth_auth_json

        # mbboauth refresh (app immediately refreshes the token)
        headers = {
            "Accept": "application/json",
            "Accept-Charset": "utf-8",
            "User-Agent": "myAudi-Android/4.5.0(Build800236547.2110181440)Android/11",
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Client-ID": self.xclientId,
        }
        mbboauth_refresh_data = {
            "grant_type": "refresh_token",
            "token": mbboauth_auth_json["refresh_token"],
            "scope": "sc2:fal",
            # "vin": vin,  << App uses a dedicated VIN here, but it works without, don't know
        }
        encoded_mbboauth_refresh_data = urlencode(mbboauth_refresh_data, encoding="utf-8").replace("+","%20")
        mbboauth_refresh_rsp, mbboauth_refresh_rsptxt = await self._api.request(
            "POST",
            self.mbbOAuthBaseURL + "/mobile/oauth2/v1/token",
            encoded_mbboauth_refresh_data,
            headers=headers,
            allow_redirects=False,
            cookies=mbboauth_client_reg_rsp.cookies,
            rsp_wtxt = True,
        )
        # this code is the old "vwToken"
        self.vwToken = json.loads(mbboauth_refresh_rsptxt)

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
