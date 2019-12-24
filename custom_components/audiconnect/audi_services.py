from abc import abstractmethod, ABCMeta
import json

from .audi_models import CurrentVehicleDataResponse, RequestStatus, VehicleDataResponse, VehiclesResponse, Vehicle
from .audi_api import AudiAPI

from hashlib import sha512

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

    async def request_current_vehicle_data(self, vin: str):
        self._api.use_token(self.vwToken)
        data = await self._api.post("https://msg.volkswagen.de/fs-car/bs/vsr/v1/{type}/{country}/vehicles/{vin}/requests".format(type=self._type, country=self._country, vin=vin))
        return CurrentVehicleDataResponse(data)

    async def get_request_status(self, vin: str, request_id: str):
        self._api.use_token(self.vwToken)
        data = await self._api.get("https://msg.volkswagen.de/fs-car/bs/vsr/v1/{type}/{country}/vehicles/{vin}/requests/{requestId}/jobstatus".format(type=self._type, country=self._country, vin=vin, requestId=request_id))
        return RequestStatus(data)

    async def get_stored_vehicle_data(self, vin: str):
        self._api.use_token(self.vwToken)
        data = await self._api.get("https://msg.volkswagen.de/fs-car/bs/vsr/v1/{type}/{country}/vehicles/{vin}/status".format(type=self._type, country=self._country, vin=vin))
        return VehicleDataResponse(data)

    async def get_charger(self, vin: str):
        self._api.use_token(self.vwToken)
        return await self._api.get("https://msg.volkswagen.de/fs-car/bs/batterycharge/v1/{type}/{country}/vehicles/{vin}/charger".format(type=self._type, country=self._country, vin=vin))

    async def get_climater(self, vin: str):
        self._api.use_token(self.vwToken)
        return await self._api.get("https://msg.volkswagen.de/fs-car/bs/climatisation/v1/{type}/{country}/vehicles/{vin}/climater".format(type=self._type, country=self._country, vin=vin))

    async def get_stored_position(self, vin: str):
        self._api.use_token(self.vwToken)
        return await self._api.get("https://msg.volkswagen.de/fs-car/bs/cf/v1/{type}/{country}/vehicles/{vin}/position".format(type=self._type, country=self._country, vin=vin))

    async def get_operations_list(self, vin: str):
        self._api.use_token(self.vwToken)
        return await self._api.get("https://mal-1a.prd.ece.vwg-connect.com/api/rolesrights/operationlist/v3/vehicles/" + vin)

    async def get_timer(self, vin: str):
        self._api.use_token(self.vwToken)
        return await self._api.get("https://msg.volkswagen.de/fs-car/bs/departuretimer/v1/{type}/{country}/vehicles/{vin}/timer".format(type="Audi", country="DE", vin=vin))
 
    async def get_vehicles(self):
        self._api.use_token(self.vwToken)
        return await self._api.get("https://msg.volkswagen.de/fs-car/usermanagement/users/v1/{type}/{country}/vehicles".format(type=self._type, country=self._country))

    async def get_vehicle_information(self):
        self._api.use_token(self.audiToken)
        data = await self._api.get("https://msg.audi.de/myaudi/vehicle-management/v1/vehicles")
        response = VehiclesResponse()
        response.parse(data)
        return response

    async def _get_security_token(self, vin: str, action: str):
        # Challenge
        headers = {
			"User-Agent": "okhttp/3.7.0",
			"X-App-Version": '3.14.0',
			"X-App-Name": 'myAudi',
            "Accept": "application/json",
            "Authorization": "Bearer " + self.vwToken.get('access_token')
		}

        body = await self._api.request('GET', "https://mal-1a.prd.ece.vwg-connect.com/api/rolesrights/authorization/v2/vehicles/" + vin + "/services/" + action + "/security-pin-auth-requested", headers=headers, data=None)
        secToken = body["securityPinAuthInfo"]["securityToken"]
        challenge = body["securityPinAuthInfo"]["securityPinTransmission"]["challenge"]

        # Response
        securityPinHash = self._generate_security_pin_hash(challenge)
        data = {
		    "securityPinAuthentication": {
			    "securityPin": {
			        "challenge": challenge,
				    "securityPinHash": securityPinHash
			    },
			    "securityToken": secToken
			}
		}

        headers = {
			"User-Agent": "okhttp/3.7.0",
            'Content-Type': 'application/json',
			"X-App-Version": '3.14.0',
			"X-App-Name": 'myAudi',
            "Accept": "application/json",
            "Authorization": "Bearer " + self.vwToken.get('access_token')
		}

        body = await self._api.request('POST', 'https://mal-1a.prd.ece.vwg-connect.com/api/rolesrights/authorization/v2/security-pin-auth-completed', headers=headers, data=json.dumps(data))
        return body["securityToken"]        

    def _GetVehicleActionHeader(self, content_type: str, security_token: str):
        headers = {
			"User-Agent": "okhttp/3.7.0",
			"Host": "msg.volkswagen.de",
			"X-App-Version": '3.14.0',
			"X-App-Name": 'myAudi',
            "Authorization": "Bearer " + self.vwToken.get('access_token'),
			"Accept-charset": "UTF-8",
			"Content-Type": content_type,
			"Accept": "application/json, application/vnd.vwg.mbb.ChargerAction_v1_0_0+xml,application/vnd.volkswagenag.com-error-v1+xml,application/vnd.vwg.mbb.genericError_v1_0_2+xml, application/vnd.vwg.mbb.RemoteStandheizung_v2_0_0+xml, application/vnd.vwg.mbb.genericError_v1_0_2+xml,application/vnd.vwg.mbb.RemoteLockUnlock_v1_0_0+xml,*/*",
		}

        if security_token != None:
            headers["x-mbbSecToken"] = security_token

        return headers

    async def set_vehicle_lock(self, vin: str, lock: bool):
        security_token = await self._get_security_token(vin, "rlu_v1/operations/" + ("LOCK" if lock else "UNLOCK"))
        data = '<?xml version="1.0" encoding= "UTF-8" ?>\n<rluAction xmlns="http://audi.de/connect/rlu">\n   <action>{action}</action>\n</rluAction>'.format(action="lock" if lock else "unlock")
        headers = self._GetVehicleActionHeader("application/vnd.vwg.mbb.RemoteLockUnlock_v1_0_0+xml", security_token)
        return await self._api.request('POST', "https://msg.volkswagen.de/fs-car/bs/rlu/v1/{type}/{country}/vehicles/{vin}/actions".format(type=self._type, country=self._country, vin=vin), headers=headers, data=data)

    async def set_pre_heater(self, vin: str, activate: bool):
        security_token = await self._get_security_token(vin, "rheating_v1/operations/P_QSACT")
        data = '<?xml version="1.0" encoding= "UTF-8" ?>\n<performAction xmlns="http://audi.de/connect/rs">\n   <quickstart>\n      <active>{action}</active>\n   </quickstart>\n</performAction>'.format(action="true" if activate else "false")
        headers = self._GetVehicleActionHeader("application/vnd.vwg.mbb.RemoteStandheizung_v2_0_0+xml", security_token)
        return await self._api.request('POST', "https://msg.volkswagen.de/fs-car/bs/rs/v1/{type}/{country}/vehicles/{vin}/action".format(type=self._type, country=self._country, vin=vin), headers=headers, data=data)
    
    async def set_battery_charger(self, vin: str, start: bool):
        data = '<?xml version="1.0" encoding= "UTF-8" ?>\n<action>\n   <type>{action}</type>\n</action>'.format(action="start" if start else "stop")
        headers = self._GetVehicleActionHeader("application/vnd.vwg.mbb.ChargerAction_v1_0_0+xml", None)
        return await self._api.request('POST', "https://msg.volkswagen.de/fs-car/bs/batterycharge/v1/{type}/{country}/vehicles/{vin}/charger/actions".format(type=self._type, country=self._country, vin=vin), headers=headers, data=data)

    async def set_climatisation(self, vin: str, start: bool):
        data = '<?xml version="1.0" encoding= "UTF-8" ?>\n<action>\n   <type>{action}</type>\n</action>'.format(action="startClimatisation" if start else "stopClimatisation")
        headers = self._GetVehicleActionHeader("application/vnd.vwg.mbb.ClimaterAction_v1_0_0+xml", None)
        return await self._api.request('POST', "https://msg.volkswagen.de/fs-car/bs/climatisation/v1/{type}/{country}/vehicles/{vin}/climater/actions".format(type=self._type, country=self._country, vin=vin), headers=headers, data=data)
    
    async def set_window_heating(self, vin: str, start: bool):
        data = '<?xml version="1.0" encoding= "UTF-8" ?>\n<action>\n   <type>{action}</type>\n</action>'.format(action="startWindowHeating" if start else "stopWindowHeating")
        headers = self._GetVehicleActionHeader("application/vnd.vwg.mbb.ClimaterAction_v1_0_0+xml", None)
        return await self._api.request('POST', "https://msg.volkswagen.de/fs-car/bs/climatisation/v1/{type}/{country}/vehicles/{vin}/climater/actions".format(type=self._type, country=self._country, vin=vin), headers=headers, data=data)
    
    async def login_request(self, user: str, password: str):
        # Get Audi Token
        self._api.use_token(None)
        data = {'client_id': 'mmiconnect_android',
                'scope': 'openid profile email mbb offline_access mbbuserid myaudi selfservice:read selfservice:write',
                'response_type': 'token id_token',
                'grant_type': 'password',
                'username': user,
                'password': password}

        self.audiToken = await self._api.post('https://id.audi.com/v1/token', data, use_json=False)

        # Get VW Token
        data = { 'grant_type':'id_token', 'token': self.audiToken.get('id_token'), 'scope': 'sc2:fal' }

        headers = {
				"User-Agent": "okhttp/3.7.0",
				"X-App-Version": '3.14.0',
				"X-App-Name": 'myAudi',
				"X-Client-Id": '77869e21-e30a-4a92-b016-48ab7d3db1d8',
				'Host': "mbboauth-1d.prd.ece.vwg-connect.com"
		}

        self.vwToken = await self._api.request('POST', 'https://mbboauth-1d.prd.ece.vwg-connect.com/mbbcoauth/mobile/oauth2/v1/token', headers=headers, data=data)

    def _to_byte_array(self, hexString):
        result = []
        for i in range(0, len(hexString), 2):
            result.append(int(hexString[i:i+2], 16))
            
        return result

    def _generate_security_pin_hash(self, challenge):
        pin = self._to_byte_array(self._spin)
        byteChallenge = self._to_byte_array(challenge)
        b = bytes(pin + byteChallenge)
        return sha512(b).hexdigest().upper()
