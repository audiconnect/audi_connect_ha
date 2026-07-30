from __future__ import annotations

import asyncio
import hmac
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from hashlib import sha512
from typing import Any
from urllib.parse import urlencode, urlparse

from bs4 import BeautifulSoup

from .audi_api import AudiAPI
from .audi_models import TripDataResponse, VehicleDataResponse, VehiclesResponse
from .const import DEFAULT_API_LEVEL
from .util import get_attr, to_byte_array


MAX_RESPONSE_ATTEMPTS = 10
REQUEST_STATUS_SLEEP = 10
MAX_LOGIN_REDIRECTS = 20
AUTH_COOKIE_DOMAINS = ("vwgroup.io", "cariad.digital", "vwg-connect.com")

SUCCEEDED = "succeeded"
FAILED = "failed"
REQUEST_SUCCESSFUL = "request_successful"
REQUEST_FAILED = "request_failed"

_LOGGER = logging.getLogger(__name__)


def _to_absolute(absolute_url: str, relative_url: str) -> str:
    """Convert a relative url to an absolute url."""
    url_parts = urlparse(absolute_url)
    return url_parts.scheme + "://" + url_parts.netloc + relative_url


class AudiService:
    def __init__(
        self, api: AudiAPI, country: str, spin: str | None, api_level: int
    ) -> None:
        self._api = api
        self._country = country
        self._language: str | None = None
        self._type = "Audi"
        self._spin = spin
        self._homeRegion: dict[str, str] = {}
        self._homeRegionSetter = {}
        self.mbbOAuthBaseURL = None
        self.mbboauthToken = None
        self.xclientId = None
        self._tokenEndpoint = ""
        self._bearer_token_json = None
        self._client_id = ""
        self._authorizationServerBaseURLLive = ""
        self._api_level = api_level

        if self._api_level is None:
            self._api_level = DEFAULT_API_LEVEL

        if self._country is None:
            self._country = "DE"

    def get_hidden_html_input_form_data(
        self, response: str, form_data: dict[str, str]
    ) -> dict[str, str]:
        # Now parse the html body and extract the target url, csrf token and other required parameters
        html = BeautifulSoup(response, "html.parser")
        form_inputs = html.find_all("input", attrs={"type": "hidden"})
        for form_input in form_inputs:
            name = form_input.get("name")
            form_data[name] = form_input.get("value")

        return form_data

    def get_post_url(self, response: str, url: str) -> str:
        # Now parse the html body and extract the target url, csrf token and other required parameters
        html = BeautifulSoup(response, "html.parser")
        form_tag = html.find("form")

        # Extract the target url
        action = form_tag.get("action")
        if action.startswith("http"):
            # Absolute url
            username_post_url = action
        elif action.startswith("/"):
            # Relative to domain
            username_post_url = _to_absolute(url, action)
        else:
            raise ValueError("Unknown form action: " + action)
        return username_post_url

    async def login(self, user: str, password: str, persist_token: bool = True) -> None:
        _LOGGER.debug("LOGIN: Starting login to Audi service...")
        await self.login_request(user, password)

    async def refresh_vehicle_data(self, vin: str):
        request_id = await self.request_current_vehicle_data(vin.upper())
        await self.check_bff_request_succeeded(vin, request_id)

    async def request_current_vehicle_data(self, vin: str):
        self._api.use_token(self._bearer_token_json)
        data = await self._api.post(
            self.__get_cariad_url_for_vin(vin, "vehiclewakeup"),
            data=None,
            use_json=False,
        )

        request_id = data.get("data", {}).get("requestID")
        if request_id is None:
            raise Exception("Vehicle wakeup response did not contain requestID")

        return request_id

    async def get_preheater(self, vin: str):
        self._api.use_token(self.vwToken)
        return await self._api.get(
            "{homeRegion}/fs-car/bs/rs/v1/{type}/{country}/vehicles/{vin}/status".format(
                homeRegion=await self._get_home_region(vin.upper()),
                type=self._type,
                country=self._country,
                vin=vin.upper(),
            )
        )

    async def get_stored_vehicle_data(self, vin: str):
        redacted_vin = "*" * (len(vin) - 4) + vin[-4:]
        JOBS2QUERY = {
            "access",
            "activeVentilation",
            "auxiliaryHeating",
            "batteryChargingCare",
            "batterySupport",
            "charging",
            "chargingProfiles",
            "chargingTimers",
            "climatisation",
            "climatisationTimers",
            "departureProfiles",
            "departureTimers",
            "fuelStatus",
            "honkAndFlash",
            "hybridCarAuxiliaryHeating",
            "lvBattery",
            "measurements",
            "oilLevel",
            "readiness",
            # "userCapabilities",
            "vehicleHealthInspection",
            "vehicleHealthWarnings",
            "vehicleLights",
        }
        self._api.use_token(self._bearer_token_json)
        data = await self._api.get(
            self.__get_cariad_url_for_vin(
                vin, "selectivestatus?jobs={jobs}", jobs=",".join(JOBS2QUERY)
            )
        )

        _LOGGER.debug("Vehicle data returned for VIN: %s: %s", redacted_vin, data)
        return VehicleDataResponse(data)

    async def get_charger(self, vin: str):
        self._api.use_token(self.vwToken)
        return await self._api.get(
            "{homeRegion}/fs-car/bs/batterycharge/v1/{type}/{country}/vehicles/{vin}/charger".format(
                homeRegion=await self._get_home_region(vin.upper()),
                type=self._type,
                country=self._country,
                vin=vin.upper(),
            )
        )

    async def get_climater(self, vin: str):
        self._api.use_token(self.vwToken)
        return await self._api.get(
            "{homeRegion}/fs-car/bs/climatisation/v1/{type}/{country}/vehicles/{vin}/climater".format(
                homeRegion=await self._get_home_region(vin.upper()),
                type=self._type,
                country=self._country,
                vin=vin.upper(),
            )
        )

    async def get_stored_position(self, vin: str):
        self._api.use_token(self._bearer_token_json)
        return await self._api.get(
            self.__get_cariad_url_for_vin(vin, "parkingposition")
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
                type=self._type,
                country=self._country,
                vin=vin.upper(),
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
            "X-App-Version": AudiAPI.HDR_XAPP_VERSION,
            "Accept-Language": "{l}-{c}".format(
                l=self._language, c=self._country.upper()
            ),
            "X-User-Country": self._country.upper(),
            "User-Agent": AudiAPI.HDR_USER_AGENT,
            "Authorization": "Bearer " + self.audiToken["access_token"],
            "Content-Type": "application/json; charset=utf-8",
        }
        req_data = {
            "query": "query vehicleList {\n userVehicles {\n vin\n mappingVin\n vehicle { core { modelYear\n }\n media { shortName\n longName }\n }\n csid\n commissionNumber\n type\n devicePlatform\n mbbConnect\n userRole {\n role\n }\n vehicle {\n classification {\n driveTrain\n }\n }\n nickname\n }\n}"
        }
        req_rsp, rep_rsptxt = await self._api.request(
            "POST",
            "https://app-api.my.aoa.audi.com/vgql/v1/graphql"
            if self._country.upper() == "US"
            else "https://app-api.live-my.audi.com/vgql/v1/graphql",  # Starting in 2023, US users need to point at the aoa (Audi of America) URL.
            json.dumps(req_data),
            headers=headers,
            allow_redirects=False,
            rsp_wtxt=True,
        )
        vins = json.loads(rep_rsptxt)
        if "errors" in vins:
            raise Exception(f"API returned errors: {vins['errors']}")

        if "data" not in vins or vins["data"] is None:
            raise Exception("No data in API response")

        if vins["data"].get("userVehicles") is None:
            raise Exception(
                "No vehicle data in API response - possible authentication issue"
            )

        response = VehiclesResponse()
        response.parse(vins["data"])
        return response

    async def get_vehicle_data(self, vin: str):
        self._api.use_token(self.vwToken)
        return await self._api.get(
            "{homeRegion}/fs-car/vehicleMgmt/vehicledata/v2/{type}/{country}/vehicles/{vin}/".format(
                homeRegion=await self._get_home_region(vin.upper()),
                type=self._type,
                country=self._country,
                vin=vin.upper(),
            )
        )

    async def get_tripdata(self, vin: str, kind: str):
        self._api.use_token(self.vwToken)

        # read tripdata
        headers = {
            "Accept": "application/json",
            "Accept-Charset": "utf-8",
            "X-App-Name": "myAudi",
            "X-App-Version": AudiAPI.HDR_XAPP_VERSION,
            "X-Client-ID": self.xclientId,
            "User-Agent": AudiAPI.HDR_USER_AGENT,
            "Authorization": "Bearer " + self.vwToken["access_token"],
        }
        td_reqdata = {
            "type": "list",
            "from": "1970-01-01T00:00:00Z",
            # "from":(datetime.now(timezone.utc) - timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "to": (datetime.now(timezone.utc) + timedelta(minutes=90)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
        }
        data = await self._api.request(
            "GET",
            "{homeRegion}/api/bs/tripstatistics/v1/vehicles/{vin}/tripdata/{kind}".format(
                homeRegion=await self._get_home_region_setter(vin.upper()),
                vin=vin.upper(),
                kind=kind,
            ),
            None,
            params=td_reqdata,
            headers=headers,
        )
        td_sorted = sorted(
            data["tripDataList"]["tripData"],
            key=lambda k: k["overallMileage"],
            reverse=True,
        )
        # _LOGGER.debug("get_tripdata: td_sorted: %s", td_sorted)
        td_current = td_sorted[0]
        # FIX, TR/2023-03-25: Assign just in case td_sorted contains only one item
        td_reset_trip = td_sorted[0]

        for trip in td_sorted:
            if (td_current["startMileage"] - trip["startMileage"]) > 2:
                td_reset_trip = trip
                break
            else:
                td_current["tripID"] = trip["tripID"]
                td_current["startMileage"] = trip["startMileage"]
        _LOGGER.debug("TRIP DATA: td_current: %s", td_current)
        _LOGGER.debug("TRIP DATA: td_reset_trip: %s", td_reset_trip)

        return TripDataResponse(td_current), TripDataResponse(td_reset_trip)

    async def _fill_home_region(self, vin: str):
        # the home-region endpoint returns
        # https://ha-5a.prd.eu.vwg.vwautocloud.net which is no valid endpoint
        # (at least not in DE region). set it statically.
        if self._country.upper() != "US" and self._api_level == 1:
            self._homeRegion[vin] = "https://mal-3a.prd.eu.dp.vwg-connect.com"
            self._homeRegionSetter[vin] = "https://mal-3a.prd.eu.dp.vwg-connect.com"
            return
        self._homeRegion[vin] = "https://msg.volkswagen.de"
        self._homeRegionSetter[vin] = "https://mal-1a.prd.ece.vwg-connect.com"

        try:
            self._api.use_token(self.vwToken)
            res = await self._api.get(
                "https://mal-1a.prd.ece.vwg-connect.com/api/cs/vds/v1/vehicles/{vin}/homeRegion".format(
                    vin=vin
                )
            )
            if (
                res is not None
                and res.get("homeRegion") is not None
                and res["homeRegion"].get("baseUri") is not None
                and res["homeRegion"]["baseUri"].get("content") is not None
            ):
                uri = res["homeRegion"]["baseUri"]["content"]
                if uri != "https://mal-1a.prd.ece.vwg-connect.com/api":
                    self._homeRegionSetter[vin] = uri.split("/api")[0]
                    self._homeRegion[vin] = self._homeRegionSetter[vin].replace(
                        "mal-", "fal-"
                    )
        except Exception:
            pass

    async def _get_home_region(self, vin: str):
        if self._homeRegion.get(vin) is not None:
            return self._homeRegion[vin]

        await self._fill_home_region(vin)

        return self._homeRegion[vin]

    async def _get_home_region_setter(self, vin: str):
        if self._homeRegionSetter.get(vin) is not None:
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
            "{homeRegionSetter}/api/rolesrights/authorization/v2/vehicles/".format(
                homeRegionSetter=await self._get_home_region_setter(vin.upper())
            )
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
            "{homeRegionSetter}/api/rolesrights/authorization/v2/security-pin-auth-completed".format(
                homeRegionSetter=await self._get_home_region_setter(vin.upper())
            ),
            headers=headers,
            data=json.dumps(data),
        )
        return body["securityToken"]

    def _get_vehicle_action_header(
        self, content_type: str, security_token: str | None, host: str | None = None
    ) -> dict[str, str]:
        if not host:
            host = (
                "mal-3a.prd.eu.dp.vwg-connect.com"
                if self._country in {"DE", "US"}
                else "msg.volkswagen.de"
            )

        headers = {
            "User-Agent": AudiAPI.HDR_USER_AGENT,
            "Host": host,
            "X-App-Version": AudiAPI.HDR_XAPP_VERSION,
            "X-App-Name": "myAudi",
            "Authorization": "Bearer " + self.vwToken.get("access_token"),
            "Accept-charset": "UTF-8",
            "Content-Type": content_type,
            "Accept": "application/json, application/vnd.vwg.mbb.ChargerAction_v1_0_0+xml,application/vnd.volkswagenag.com-error-v1+xml,application/vnd.vwg.mbb.genericError_v1_0_2+xml, application/vnd.vwg.mbb.RemoteStandheizung_v2_0_0+xml, application/vnd.vwg.mbb.genericError_v1_0_2+xml,application/vnd.vwg.mbb.RemoteLockUnlock_v1_0_0+xml,*/*",
        }

        if security_token:
            headers["x-securityToken"] = security_token

        return headers

    def __build_url(
        self, base_url: str, path_and_query: str, **path_and_query_kwargs: Any
    ) -> str:
        action_path = path_and_query.format(**path_and_query_kwargs)

        return base_url.rstrip("/") + "/" + action_path.lstrip("/")

    def __get_cariad_url(
        self, path_and_query: str, **path_and_query_kwargs: Any
    ) -> str:
        base_url = "https://{region}.bff.cariad.digital".format(
            region="emea" if self._country.upper() != "US" else "na"
        )

        return self.__build_url(base_url, path_and_query, **path_and_query_kwargs)

    def __get_cariad_url_for_vin(
        self, vin: str, path_and_query: str, **path_and_query_kwargs: Any
    ) -> str:
        base_url = self.__get_cariad_url("/vehicle/v1/vehicles/{vin}", vin=vin.upper())

        return self.__build_url(base_url, path_and_query, **path_and_query_kwargs)

    async def set_vehicle_lock(self, vin: str, lock: bool):
        security_token = await self._get_security_token(
            vin, "rlu_v1/operations/" + ("LOCK" if lock else "UNLOCK")
        )
        # deprecated data removed on 24Mar2025
        # data = '<?xml version="1.0" encoding= "UTF-8" ?><rluAction xmlns="http://audi.de/connect/rlu"><action>{action}</action></rluAction>'.format(
        #     action="lock" if lock else "unlock"
        # )
        data = None

        headers = self._get_vehicle_action_header(
            "application/vnd.vwg.mbb.RemoteLockUnlock_v1_0_0+xml", security_token
        )
        res = await self._api.request(
            "POST",
            "{homeRegionSetter}/api/bs/rlu/v1/vehicles/{vin}/{action}".format(
                homeRegionSetter=await self._get_home_region_setter(vin.upper()),
                vin=vin.upper(),
                action="lock" if lock else "unlock",
            ),
            headers=headers,
            data=data,
        )

        checkUrl = "{homeRegionSetter}/api/bs/rlu/v1/vehicles/{vin}/requests/{requestId}/status".format(
            homeRegionSetter=await self._get_home_region_setter(vin.upper()),
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

    async def set_battery_charger(self, vin: str, start: bool, timer: bool):
        if start and timer:
            data = {"preferredChargeMode": "timer"}
        elif start:
            data = {"preferredChargeMode": "manual"}
        else:
            raise NotImplementedError(
                "The 'Stop Charger' service is deprecated and will be removed in a future release."
            )

        data = json.dumps(data)
        headers = {"Authorization": "Bearer " + self._bearer_token_json["access_token"]}

        await self._api.request(
            "PUT",
            self.__get_cariad_url_for_vin(vin, "charging/mode"),
            headers=headers,
            data=data,
        )

        # checkUrl = "{homeRegion}/fs-car/bs/batterycharge/v1/{type}/{country}/vehicles/{vin}/charger/actions/{actionid}".format(
        #     homeRegion=await self._get_home_region(vin.upper()),
        #     type=self._type,
        #     country=self._country,
        #     vin=vin.upper(),
        #     actionid=res["action"]["actionId"],
        # )

        # await self.check_request_succeeded(
        #     checkUrl,
        #     "start charger" if start else "stop charger",
        #     SUCCEEDED,
        #     FAILED,
        #     "action.actionState",
        # )

    async def set_target_state_of_charge(self, vin: str, target_soc: int):
        """Set the target state of charge (battery percentage)."""
        if not (20 <= target_soc <= 100):
            raise ValueError(
                "Target state of charge must be between 20 and 100 percent"
            )

        # Use Cariad BFF API (requires API level 1)
        headers = {"Authorization": "Bearer " + self._bearer_token_json["access_token"]}

        data = {"targetSOC_pct": target_soc}

        await self._api.request(
            "PUT",
            self.__get_cariad_url_for_vin(vin, "charging/settings"),
            headers=headers,
            data=json.dumps(data),
        )

    async def set_climatisation(self, vin: str, start: bool):
        api_level = self._api_level
        country = self._country

        if start:
            raise NotImplementedError(
                "The 'Start Climatisation (Legacy)' service is deprecated and no longer functional. "
                "Please use the 'Start Climate Control' service instead."
            )
            # data = '{"action":{"type": "startClimatisation","settings": {"targetTemperature": 2940,"climatisationWithoutHVpower": true,"heaterSource": "electric","climaterElementSettings": {"isClimatisationAtUnlock": false, "isMirrorHeatingEnabled": true,}}}}'
        else:
            if api_level == 0:
                data = '{"action":{"type": "stopClimatisation"}}'

                if country == "US":
                    headers = self._get_vehicle_action_header("application/json", None)
                    res = await self._api.request(
                        "POST",
                        "https://mal-3a.prd.eu.dp.vwg-connect.com/api/bs/climatisation/v1/vehicles/{vin}/climater/actions".format(
                            vin=vin.upper(),
                        ),
                        headers=headers,
                        data=data,
                    )
                    checkUrl = "https://mal-3a.prd.eu.dp.vwg-connect.com/api/bs/climatisation/v1/vehicles/{vin}/climater/actions/{actionid}".format(
                        vin=vin.upper(),
                        actionid=res["action"]["actionId"],
                    )

                else:
                    headers = self._get_vehicle_action_header(
                        "application/json", None, "msg.volkswagen.de"
                    )
                    res = await self._api.request(
                        "POST",
                        "{homeRegion}/fs-car/bs/climatisation/v1/{type}/{country}/vehicles/{vin}/climater/actions".format(
                            homeRegion=await self._get_home_region(vin.upper()),
                            type=self._type,
                            country=self._country,
                            vin=vin.upper(),
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
                    "stop climatisation",
                    SUCCEEDED,
                    FAILED,
                    "action.actionState",
                )

            elif api_level == 1:
                data = None
                headers = {
                    "Authorization": "Bearer " + self._bearer_token_json["access_token"]
                }
                res = await self._api.request(
                    "POST",
                    self.__get_cariad_url_for_vin(vin, "climatisation/stop"),
                    headers=headers,
                    data=data,
                )

                # checkUrl = "https://emea.bff.cariad.digital/vehicle/v1/vehicles/{vin}/pendingrequests".format(
                #     vin=vin.upper(),
                #     actionid=res["action"]["actionId"],
                # )

                # await self.check_request_succeeded(
                #     checkUrl,
                #     "startClimatisation",
                #     SUCCEEDED,
                #     FAILED,
                #     "action.actionState",
                # )

    async def start_climate_control(
        self,
        vin: str,
        temp_f: int,
        temp_c: int,
        glass_heating: bool,
        seat_fl: bool,
        seat_fr: bool,
        seat_rl: bool,
        seat_rr: bool,
        climatisation_at_unlock: bool = False,
        climatisation_mode: str = "comfort",
    ):
        api_level = self._api_level
        country = self._country
        target_temperature = None

        _LOGGER.debug(
            f"Attempting to start climate control with API Level {api_level} and country {country}."
        )

        if api_level == 0:
            target_temperature = None
            if temp_f is not None:
                target_temperature = int(((temp_f - 32) * (5 / 9)) * 10 + 2731)
            elif temp_c is not None:
                target_temperature = int(temp_c * 10 + 2731)

            # Default Temp
            target_temperature = target_temperature or 2941

            # Construct Zone Settings
            zone_settings = [
                {"value": {"isEnabled": seat_fl, "position": "frontLeft"}},
                {"value": {"isEnabled": seat_fr, "position": "frontRight"}},
                {"value": {"isEnabled": seat_rl, "position": "rearLeft"}},
                {"value": {"isEnabled": seat_rr, "position": "rearRight"}},
            ]

            data = {
                "action": {
                    "type": "startClimatisation",
                    "settings": {
                        "targetTemperature": target_temperature,
                        "climatisationWithoutHVpower": True,
                        "heaterSource": "electric",
                        "climaterElementSettings": {
                            "isClimatisationAtUnlock": climatisation_at_unlock,
                            "isMirrorHeatingEnabled": glass_heating,
                            "zoneSettings": {"zoneSetting": zone_settings},
                        },
                    },
                }
            }

            data = json.dumps(data)

            if country == "US":
                headers = self._get_vehicle_action_header("application/json", None)
                res = await self._api.request(
                    "POST",
                    "https://mal-3a.prd.eu.dp.vwg-connect.com/api/bs/climatisation/v1/vehicles/{vin}/climater/actions".format(
                        vin=vin.upper(),
                    ),
                    headers=headers,
                    data=data,
                )

                checkUrl = "https://mal-3a.prd.eu.dp.vwg-connect.com/api/bs/climatisation/v1/vehicles/{vin}/climater/actions/{actionid}".format(
                    vin=vin.upper(),
                    actionid=res["action"]["actionId"],
                )
            else:
                headers = self._get_vehicle_action_header(
                    "application/json", None, "msg.volkswagen.de"
                )
                res = await self._api.request(
                    "POST",
                    "{homeRegion}/fs-car/bs/climatisation/v1/{type}/{country}/vehicles/{vin}/climater/actions".format(
                        homeRegion=await self._get_home_region(vin.upper()),
                        type=self._type,
                        country=self._country,
                        vin=vin.upper(),
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
                "startClimatisation",
                SUCCEEDED,
                FAILED,
                "action.actionState",
            )

        elif api_level == 1:
            if temp_f is not None:
                target_temperature = int((temp_f - 32) * (5 / 9))
            elif temp_c is not None:
                target_temperature = int(temp_c)

            target_temperature = target_temperature or 21

            data = {
                "climatisationMode": climatisation_mode,
                "targetTemperature": target_temperature,
                "targetTemperatureUnit": "celsius",
                "climatisationWithoutExternalPower": True,
                "climatizationAtUnlock": climatisation_at_unlock,
                "windowHeatingEnabled": glass_heating,
                "zoneFrontLeftEnabled": seat_fl,
                "zoneFrontRightEnabled": seat_fr,
                "zoneRearLeftEnabled": seat_rl,
                "zoneRearRightEnabled": seat_rr,
            }

            data = json.dumps(data)
            headers = {
                "Authorization": "Bearer " + self._bearer_token_json["access_token"]
            }
            res = await self._api.request(
                "POST",
                self.__get_cariad_url_for_vin(vin, "climatisation/start"),
                headers=headers,
                data=data,
            )

            # checkUrl = "https://emea.bff.cariad.digital/vehicle/v1/vehicles/{vin}/pendingrequests".format(
            #     vin=vin.upper(),
            #     actionid=res["action"]["actionId"],
            # )

            # await self.check_request_succeeded(
            #     checkUrl,
            #     "startClimatisation",
            #     SUCCEEDED,
            #     FAILED,
            #     "action.actionState",
            # )

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
                type=self._type,
                country=self._country,
                vin=vin.upper(),
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

    async def set_pre_heater(
        self, vin: str, activate: bool, duration: int | None = None
    ) -> None:
        if activate:
            if not duration:
                duration = 30
            data = {
                "duration_min": int(duration),
                "spin": self._spin,
            }

            data = json.dumps(data)
        else:
            data = None

        headers = {
            "Accept": "application/json",
            "Accept-charset": "utf-8",
            "Authorization": "Bearer " + self._bearer_token_json["access_token"],
            "User-Agent": AudiAPI.HDR_USER_AGENT,
            "Content-Type": "application/json; charset=utf-8",
            "Accept-encoding": "gzip",
        }
        res = await self._api.request(
            "POST",
            self.__get_cariad_url_for_vin(
                vin, "auxiliaryheating/{action}", action="start" if activate else "stop"
            ),
            headers=headers,
            data=data,
        )

        await self.check_bff_request_succeeded(vin, res["data"]["requestID"])

    async def start_engine(self, vin: str) -> None:
        if self._spin is None:
            raise Exception("S-PIN is required to start the engine")

        headers = {
            "Accept": "application/json",
            "Accept-charset": "utf-8",
            "Authorization": "Bearer " + self._bearer_token_json["access_token"],
            "User-Agent": AudiAPI.HDR_USER_AGENT,
            "Content-Type": "application/json; charset=utf-8",
            "Accept-encoding": "gzip",
        }

        # Step 1: Obtain userPromptProof
        proof_res = await self._api.request(
            "PUT",
            self.__get_cariad_url(
                "/vehicle/v1/engine/{vin}/userpromptproof", vin=vin.upper()
            ),
            headers=headers,
            data=json.dumps({"spin": self._spin}),
        )
        user_prompt_proof = proof_res["userPromptProof"]

        # Step 2: Submit start request
        res = await self._api.request(
            "POST",
            self.__get_cariad_url("/vehicle/v1/engine/{vin}/start", vin=vin.upper()),
            headers=headers,
            data=json.dumps(
                {
                    "securedActivationData": user_prompt_proof,
                    "spin": self._spin,
                }
            ),
        )

        await self.check_bff_request_succeeded(vin, res["data"]["requestID"])

    async def stop_engine(self, vin: str) -> None:
        headers = {
            "Accept": "application/json",
            "Accept-charset": "utf-8",
            "Authorization": "Bearer " + self._bearer_token_json["access_token"],
            "User-Agent": AudiAPI.HDR_USER_AGENT,
            "Content-Type": "application/json; charset=utf-8",
            "Accept-encoding": "gzip",
        }

        res = await self._api.request(
            "POST",
            self.__get_cariad_url("/vehicle/v1/engine/{vin}/stop", vin=vin.upper()),
            headers=headers,
            data=None,
        )

        await self.check_bff_request_succeeded(vin, res["data"]["requestID"])

    async def check_bff_request_succeeded(self, vin: str, request_id: str):
        headers = {
            "Accept": "application/json",
            "Accept-charset": "utf-8",
            "Authorization": "Bearer " + self._bearer_token_json["access_token"],
            "User-Agent": AudiAPI.HDR_USER_AGENT,
            "Content-Type": "application/json; charset=utf-8",
            "Accept-encoding": "gzip",
        }

        for _ in range(MAX_RESPONSE_ATTEMPTS):
            await asyncio.sleep(REQUEST_STATUS_SLEEP)
            res = await self._api.request(
                "GET",
                "https://{homeRegion}.bff.cariad.digital/vehicle/v1/vehicles/{vin}/pendingrequests".format(
                    homeRegion="na" if self._country.upper() == "US" else "emea",
                    vin=vin.upper(),
                ),
                headers=headers,
                data=None,
            )

            for pending_request in res["data"]:
                if pending_request["id"] == request_id:
                    if pending_request["status"] == "in_progress":
                        break  # continue waiting

                    if pending_request["status"] == "successful":
                        return

                    raise Exception(
                        "Request {} reached unexpected status {}".format(
                            request_id, pending_request["status"]
                        )
                    )

        raise Exception(f"Request {request_id} timed out")

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

        raise Exception(f"Cannot {action}, operation timed out")

    # TR/2022-12-20: New secret for X_QMAuth
    def _calculate_X_QMAuth(self) -> str:
        # Calculate X-QMAuth value
        gmtime_100sec = int(
            (
                datetime.now(timezone.utc) - datetime(1970, 1, 1, tzinfo=timezone.utc)
            ).total_seconds()
            / 100
        )
        xqmauth_secret = bytes(
            [
                26,
                256 - 74,
                256 - 103,
                37,
                256 - 84,
                23,
                256 - 102,
                256 - 86,
                78,
                256 - 125,
                256 - 85,
                256 - 26,
                113,
                256 - 87,
                71,
                109,
                23,
                100,
                24,
                256 - 72,
                91,
                256 - 41,
                6,
                256 - 15,
                67,
                108,
                256 - 95,
                91,
                256 - 26,
                71,
                256 - 104,
                256 - 100,
            ]
        )
        xqmauth_val = hmac.new(
            xqmauth_secret,
            str(gmtime_100sec).encode("ascii", "ignore"),
            digestmod="sha256",
        ).hexdigest()

        # v1:01da27b0:fbdb6e4ba3109bc68040cb83f380796f4d3bb178a626c4cc7e166815b806e4b5
        return "v1:01da27b0:" + xqmauth_val

    # TR/2021-12-01: Refresh token before it expires
    # returns True when refresh was required and successful, otherwise False
    async def refresh_token_if_necessary(self, elapsed_sec: int) -> bool:
        # The device-code flow issues an IDK bearer token with its own
        # refresh_token. The BFF refreshes it without any assertion header or
        # client_secret, so we drive the refresh off _bearer_token_json.
        if self._bearer_token_json is None:
            return False
        if "refresh_token" not in self._bearer_token_json:
            return False
        if "expires_in" not in self._bearer_token_json:
            return False

        if (elapsed_sec + 5 * 60) < self._bearer_token_json["expires_in"]:
            # refresh not needed now
            return False

        try:
            # Refresh the IDK bearer token directly against the Cariad BFF.
            headers = {
                "Accept": "application/json",
                "Accept-Charset": "utf-8",
                "User-Agent": AudiAPI.HDR_USER_AGENT,
                "Content-Type": "application/x-www-form-urlencoded",
            }
            bearer_refresh_data = urlencode(
                {
                    "client_id": self._client_id,
                    "grant_type": "refresh_token",
                    "refresh_token": self._bearer_token_json["refresh_token"],
                },
                encoding="utf-8",
            ).replace("+", "%20")
            bearer_token_rsp, bearer_token_rsptxt = await self._api.request(
                "POST",
                self._tokenEndpoint,
                bearer_refresh_data,
                headers=headers,
                allow_redirects=False,
                rsp_wtxt=True,
            )
            refreshed = json.loads(bearer_token_rsptxt)
            if "access_token" not in refreshed:
                raise Exception("Bearer token refresh returned no access_token")
            # The BFF may omit a fresh refresh_token; keep the previous one then.
            if "refresh_token" not in refreshed and "refresh_token" in (
                self._bearer_token_json or {}
            ):
                refreshed["refresh_token"] = self._bearer_token_json["refresh_token"]
            self._bearer_token_json = refreshed

            # AZS token (Audi-specific services)
            headers = {
                "Accept": "application/json",
                "Accept-Charset": "utf-8",
                "X-App-Version": AudiAPI.HDR_XAPP_VERSION,
                "X-App-Name": "myAudi",
                "User-Agent": AudiAPI.HDR_USER_AGENT,
                "Content-Type": "application/json; charset=utf-8",
            }
            asz_req_data = {
                "token": self._bearer_token_json["access_token"],
                "grant_type": "id_token",
                "stage": "live",
                "config": "myaudi",
            }
            azs_token_rsp, azs_token_rsptxt = await self._api.request(
                "POST",
                self._authorizationServerBaseURLLive + "/token",
                json.dumps(asz_req_data),
                headers=headers,
                allow_redirects=False,
                rsp_wtxt=True,
            )
            self.audiToken = json.loads(azs_token_rsptxt)

            # Re-derive the legacy vwToken from the refreshed id_token.
            if "id_token" in self._bearer_token_json and self.xclientId:
                headers = {
                    "Accept": "application/json",
                    "Accept-Charset": "utf-8",
                    "User-Agent": AudiAPI.HDR_USER_AGENT,
                    "Content-Type": "application/x-www-form-urlencoded",
                    "X-Client-ID": self.xclientId,
                }
                mbboauth_auth_data = urlencode(
                    {
                        "grant_type": "id_token",
                        "token": self._bearer_token_json["id_token"],
                        "scope": "sc2:fal",
                    },
                    encoding="utf-8",
                ).replace("+", "%20")
                _mbb_rsp, mbb_txt = await self._api.request(
                    "POST",
                    self.mbbOAuthBaseURL + "/mobile/oauth2/v1/token",
                    mbboauth_auth_data,
                    headers=headers,
                    allow_redirects=False,
                    rsp_wtxt=True,
                )
                mbb_json = json.loads(mbb_txt)
                self.mbboauthToken = mbb_json
                self.vwToken = mbb_json

            return True

        except Exception as exception:
            _LOGGER.error("Refresh token failed: " + str(exception))
            return False

    # TR/2021-12-01 updated to match behaviour of Android myAudi 4.5.0
    async def login_request(self, user: str, password: str):
        self._api.use_token(None)
        self._api.set_xclient_id(None)
        self.xclientId = None

        # The shared HA aiohttp session accumulates an authenticated SSO
        # cookie from earlier logins. On a re-login the IdP then serves a
        # consent page instead of the password page, which breaks the
        # device-flow form parsing (CSRF/HMAC/relayState missing). Start
        # each login from a clean cookie state.
        self._api.clear_cookies_for_domains(AUTH_COOKIE_DOMAINS)

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
        marketcfg_url = "https://content.app.my.audi.com/service/mobileapp/configurations/market/{c}/{l}?v=4.23.1".format(
            c=self._country, l=self._language
        )
        openidcfg_url = self.__get_cariad_url("/auth/v1/idk/oidc/openid-configuration")

        # get market config
        marketcfg_json = await self._api.request("GET", marketcfg_url, None)

        # use dynamic config from marketcfg
        self._client_id = "09b6cbec-cd19-4589-82fd-363dfa8c24da@apps_vw-dilab_com"
        if "idkClientIDAndroidLive" in marketcfg_json:
            self._client_id = marketcfg_json["idkClientIDAndroidLive"]

        self._authorizationServerBaseURLLive = self.__get_cariad_url("/login/v1/audi")

        if "authorizationServerBaseURLLive" in marketcfg_json:
            self._authorizationServerBaseURLLive = marketcfg_json[
                "myAudiAuthorizationServerProxyServiceURLProduction"
            ]
        self.mbbOAuthBaseURL = "https://mbboauth-1d.prd.ece.vwg-connect.com/mbbcoauth"
        if "mbbOAuthBaseURLLive" in marketcfg_json:
            self.mbbOAuthBaseURL = marketcfg_json["mbbOAuthBaseURLLive"]

        if "idkLoginServiceConfigurationURLProduction" in marketcfg_json:
            openidcfg_url = marketcfg_json["idkLoginServiceConfigurationURLProduction"]
            _LOGGER.debug(
                "Using idkLoginServiceConfigurationURLProduction from market config: %s",
                openidcfg_url,
            )
        else:
            _LOGGER.debug(
                "idkLoginServiceConfigurationURLProduction not found in market config, "
                "falling back to CARIAD default: %s",
                openidcfg_url,
            )

        # get openId config
        openidcfg_json = await self._api.request("GET", openidcfg_url, None)

        # use dynamic config from openId config
        self._tokenEndpoint = self.__get_cariad_url("/auth/v1/idk/oidc/token")

        if "token_endpoint" in openidcfg_json:
            self._tokenEndpoint = openidcfg_json["token_endpoint"]
        # revocation_endpoint = self.__get_cariad_base_url("/login/v1/idk/revoke")
        # if "revocation_endpoint" in openidcfg_json:
        # revocation_endpoint = openidcfg_json["revocation_endpoint"]

        # myAudi OAuth 2.0 Device Code Flow.
        #
        # Since ~2026-05, CARIAD binds the classic authorization_code exchange to
        # a Play Integrity / x-assertion header that only the genuine app can
        # produce, so exchanging the code at the IDK token endpoint returns
        # HTTP 400 {"error":"invalid assertion headers"}. The device-code flow
        # issues tokens directly against identity.vwgroup.io, which the BFF
        # accepts without any assertion header. We drive the user confirmation
        # server-side with username/password so the whole login stays headless.
        # Flow verified against the myAudi 5.4.1 Android app.
        idp_authorization_url = (
            "https://identity.vwgroup.io/oidc/v1/device_authorization"
        )
        idp_token_url = "https://identity.vwgroup.io/oidc/v1/token"
        signin_base = "https://identity.vwgroup.io/signin-service/v1/{cid}".format(
            cid=self._client_id
        )
        device_scope = (
            "openid profile email address phone vin badge mbb cars dealers "
            "birthdate name nickname picture profession nationalIdentifier nationality"
        )

        headers = {
            "Accept": "application/json",
            "Accept-Charset": "utf-8",
            "X-App-Version": AudiAPI.HDR_XAPP_VERSION,
            "X-App-Name": "myAudi",
            "User-Agent": AudiAPI.HDR_USER_AGENT,
        }

        # Step 1: initiate device_authorization
        device_init_data = urlencode(
            {"client_id": self._client_id, "scope": device_scope}, encoding="utf-8"
        ).replace("+", "%20")
        device_init = await self._api.request(
            "POST",
            idp_authorization_url,
            device_init_data,
            headers={
                **headers,
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        if not device_init or "device_code" not in device_init:
            raise Exception(f"device_authorization response invalid: {device_init}")
        device_code = device_init["device_code"]

        # Step 2: open the verification page, following redirects to the login form
        verif_url, verif_txt = await self._follow_login_redirects(
            device_init["verification_uri_complete"], headers
        )
        if "email" not in verif_txt.lower():
            raise Exception("Login form not found at " + verif_url[:80])

        # Step 3: submit the email at login/identifier
        id_form = self.get_hidden_html_input_form_data(verif_txt, {"email": user})
        id_rsp, id_txt = await self._api.request(
            "POST",
            signin_base + "/login/identifier",
            urlencode(id_form, encoding="utf-8").replace("+", "%20"),
            headers={**headers, "Content-Type": "application/x-www-form-urlencoded"},
            allow_redirects=True,
            rsp_wtxt=True,
        )

        # Extract csrf/hmac/relayState from the embedded JS on the password page
        csrf = None
        if "csrf_token: '" in id_txt:
            csrf = id_txt.split("csrf_token: '", 1)[1].split("'", 1)[0]
        hmac_val = None
        if '"hmac":"' in id_txt:
            hmac_val = id_txt.split('"hmac":"', 1)[1].split('"', 1)[0]
        relay_state = None
        if '"relayState":"' in id_txt:
            relay_state = id_txt.split('"relayState":"', 1)[1].split('"', 1)[0]
        if not (csrf and hmac_val and relay_state):
            raise Exception(
                "Could not extract CSRF/HMAC/relayState from the password page. "
                "Audi may be showing a consent or terms-of-service prompt. Please "
                "log in to myAudi via a browser or the app and accept any pending "
                "agreements, then restart the integration."
            )

        # Step 4: submit the password at login/authenticate
        auth_rsp, _auth_txt = await self._api.request(
            "POST",
            signin_base + "/login/authenticate",
            urlencode(
                {
                    "_csrf": csrf,
                    "email": user,
                    "password": password,
                    "hmac": hmac_val,
                    "relayState": relay_state,
                },
                encoding="utf-8",
            ).replace("+", "%20"),
            headers={**headers, "Content-Type": "application/x-www-form-urlencoded"},
            allow_redirects=False,
            rsp_wtxt=True,
        )
        if auth_rsp.status != 302 or "Location" not in auth_rsp.headers:
            raise Exception(
                "login/authenticate failed (HTTP %d) - likely invalid credentials"
                % auth_rsp.status
            )
        next_url = auth_rsp.headers["Location"]
        if next_url.startswith("/"):
            next_url = "https://identity.vwgroup.io" + next_url

        # Step 5: follow redirects to the device confirmation page and approve it
        conf_url, conf_txt = await self._follow_login_redirects(next_url, headers)
        form_action = re.search(
            r'<form[^>]+action=["\']([^"\']+)["\']', conf_txt, re.IGNORECASE
        )
        if form_action:
            allow_action = form_action.group(1)
            if allow_action.startswith("/"):
                allow_action = "https://identity.vwgroup.io" + allow_action
            csrf2 = re.search(
                r'name=["\']_csrf["\'][^>]*value=["\']([^"\']+)["\']',
                conf_txt,
                re.IGNORECASE,
            )
            if not csrf2:
                raise Exception("No _csrf token in device confirmation form")
            client_identity_name = re.search(
                r'name=["\']client_identity_name["\'][^>]*value=["\']([^"\']+)["\']',
                conf_txt,
                re.IGNORECASE,
            )
            await self._api.request(
                "POST",
                allow_action,
                urlencode(
                    {
                        "_csrf": csrf2.group(1),
                        "client_identity_name": client_identity_name.group(1)
                        if client_identity_name
                        else "myAudi App",
                        "allow": "",
                    },
                    encoding="utf-8",
                ).replace("+", "%20"),
                headers={
                    **headers,
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                allow_redirects=False,
                rsp_wtxt=True,
            )

        # Step 6: poll the IDP token endpoint until the device code is authorized
        poll_data = urlencode(
            {
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "device_code": device_code,
                "client_id": self._client_id,
            },
            encoding="utf-8",
        ).replace("+", "%20")
        interval = max(int(device_init.get("interval", 1)), 1)
        deadline = datetime.now(timezone.utc) + timedelta(
            seconds=min(int(device_init.get("expires_in", 120)), 120)
        )
        tokens = None
        while datetime.now(timezone.utc) < deadline:
            poll = await self._api.request(
                "POST",
                idp_token_url,
                poll_data,
                headers={
                    **headers,
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
            if poll and "access_token" in poll:
                tokens = poll
                break
            error = poll.get("error") if poll else None
            if error == "authorization_pending":
                await asyncio.sleep(interval)
                continue
            if error == "slow_down":
                interval += 1
                await asyncio.sleep(interval)
                continue
            raise Exception(f"Device token polling failed: {poll}")
        if tokens is None:
            raise Exception("Device token polling timed out")

        # These IDK tokens are accepted directly by the Cariad BFF.
        self._bearer_token_json = tokens

        # AZS token (Audi-specific services, used by get_vehicle_information)
        headers = {
            "Accept": "application/json",
            "Accept-Charset": "utf-8",
            "X-App-Version": AudiAPI.HDR_XAPP_VERSION,
            "X-App-Name": "myAudi",
            "User-Agent": AudiAPI.HDR_USER_AGENT,
            "Content-Type": "application/json; charset=utf-8",
        }
        asz_req_data = {
            "token": self._bearer_token_json["access_token"],
            "grant_type": "id_token",
            "stage": "live",
            "config": "myaudi",
        }
        azs_token_rsp, azs_token_rsptxt = await self._api.request(
            "POST",
            self._authorizationServerBaseURLLive + "/token",
            json.dumps(asz_req_data),
            headers=headers,
            allow_redirects=False,
            rsp_wtxt=True,
        )
        self.audiToken = json.loads(azs_token_rsptxt)

        # mbboauth client register
        headers = {
            "Accept": "application/json",
            "Accept-Charset": "utf-8",
            "User-Agent": AudiAPI.HDR_USER_AGENT,
            "Content-Type": "application/json; charset=utf-8",
        }
        mbboauth_reg_data = {
            "client_name": "SM-A405FN",
            "platform": "google",
            "client_brand": "Audi",
            "appName": "myAudi",
            "appVersion": AudiAPI.HDR_XAPP_VERSION,
            "appId": "de.myaudi.mobile.assistant",
        }
        mbboauth_client_reg_rsp, mbboauth_client_reg_rsptxt = await self._api.request(
            "POST",
            self.mbbOAuthBaseURL + "/mobile/register/v1",
            json.dumps(mbboauth_reg_data),
            headers=headers,
            allow_redirects=False,
            rsp_wtxt=True,
        )
        mbboauth_client_reg_json = json.loads(mbboauth_client_reg_rsptxt)
        self.xclientId = mbboauth_client_reg_json["client_id"]
        self._api.set_xclient_id(self.xclientId)

        # mbboauth auth: exchange the IDK id_token for the legacy vwToken
        headers = {
            "Accept": "application/json",
            "Accept-Charset": "utf-8",
            "User-Agent": AudiAPI.HDR_USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Client-ID": self.xclientId,
        }
        mbboauth_auth_data = {
            "grant_type": "id_token",
            "token": self._bearer_token_json["id_token"],
            "scope": "sc2:fal",
        }
        encoded_mbboauth_auth_data = urlencode(
            mbboauth_auth_data, encoding="utf-8"
        ).replace("+", "%20")
        mbboauth_auth_rsp, mbboauth_auth_rsptxt = await self._api.request(
            "POST",
            self.mbbOAuthBaseURL + "/mobile/oauth2/v1/token",
            encoded_mbboauth_auth_data,
            headers=headers,
            allow_redirects=False,
            rsp_wtxt=True,
        )
        mbboauth_auth_json = json.loads(mbboauth_auth_rsptxt)
        # store token and expiration time
        self.mbboauthToken = mbboauth_auth_json
        self.vwToken = mbboauth_auth_json

    async def _follow_login_redirects(
        self, start_url: str, headers: dict[str, str]
    ) -> tuple[str, str]:
        """Follow the identity.vwgroup.io redirect chain, returning the final
        (url, body) once a non-redirect page is reached."""
        url = start_url
        for _ in range(MAX_LOGIN_REDIRECTS):
            rsp, txt = await self._api.request(
                "GET",
                url,
                None,
                headers=headers,
                allow_redirects=False,
                rsp_wtxt=True,
            )
            if 300 <= rsp.status < 400 and "Location" in rsp.headers:
                nxt = rsp.headers["Location"]
                if nxt.startswith("/"):
                    parts = urlparse(url)
                    nxt = parts.scheme + "://" + parts.netloc + nxt
                url = nxt
                continue
            if rsp.status >= 400:
                raise Exception("HTTP %d while following login redirect" % rsp.status)
            return url, txt
        raise Exception("Too many redirects during login")

    def _generate_security_pin_hash(self, challenge: str) -> str:
        if self._spin is None:
            raise Exception("sPin is required to perform this action")

        pin = to_byte_array(self._spin)
        byteChallenge = to_byte_array(challenge)
        b = bytes(pin + byteChallenge)
        return sha512(b).hexdigest().upper()


__all__ = ["AudiService"]
