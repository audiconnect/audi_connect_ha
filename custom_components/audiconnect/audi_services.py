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

MAX_RESPONSE_ATTEMPTS = 10
REQUEST_STATUS_SLEEP = 10

SUCCEEDED = "succeeded"
FAILED = "failed"
REQUEST_SUCCESSFUL = "request_successful"
REQUEST_FAILED = "request_failed"


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
                type="Audi", country=self._country, vin=vin.upper()
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
            "https://msg.audi.de/myaudi/vehicle-management/v1/vehicles"
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

    async def login_request(self, user: str, password: str):
        # Get Audi Token
        self._api.use_token(None)
        data = {
            "client_id": "mmiconnect_android",
            "scope": "openid profile email mbb offline_access mbbuserid myaudi selfservice:read selfservice:write",
            "response_type": "token id_token",
            "grant_type": "password",
            "username": user,
            "password": password,
        }

        self.audiToken = await self._api.post(
            "https://id.audi.com/v1/token", data, use_json=False
        )

        # Get VW Token
        data = {
            "grant_type": "id_token",
            "token": self.audiToken.get("id_token"),
            "scope": "sc2:fal",
        }

        headers = {
            "User-Agent": "okhttp/3.7.0",
            "X-App-Version": "3.14.0",
            "X-App-Name": "myAudi",
            "X-Client-Id": "77869e21-e30a-4a92-b016-48ab7d3db1d8",
            "Host": "mbboauth-1d.prd.ece.vwg-connect.com",
        }

        self.vwToken = await self._api.request(
            "POST",
            "https://mbboauth-1d.prd.ece.vwg-connect.com/mbbcoauth/mobile/oauth2/v1/token",
            headers=headers,
            data=data,
        )

    def _generate_security_pin_hash(self, challenge):
        pin = to_byte_array(self._spin)
        byteChallenge = to_byte_array(challenge)
        b = bytes(pin + byteChallenge)
        return sha512(b).hexdigest().upper()

