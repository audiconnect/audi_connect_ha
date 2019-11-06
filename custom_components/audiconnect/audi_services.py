from audiapi.API import Token
from audiapi.model.CurrentVehicleDataResponse import CurrentVehicleDataResponse
from audiapi.model.RequestStatus import RequestStatus
from audiapi.model.Vehicle import VehiclesResponse, Vehicle
from audiapi.model.VehicleDataResponse import VehicleDataResponse

from audiapi.Services import VehicleService, Service

class AudiChargerService(VehicleService):
    async def get_charger(self):
        return await self._api.get(self.url('/vehicles/{vin}/charger'))

    def _get_path(self):
        return 'bs/batterycharge/v1'

class AudiCarFinderService(VehicleService):
    """
    Requires special permissions - might be for rental car companies
    """

    async def find(self):
        """
        Returns the position of the car
        """
        return await self._api.get(self.url('/vehicles/{vin}/position'))

    def _get_path(self):
        return 'bs/cf/v1'


class AudiCarService(Service):
    async def get_vehicles(self):
        """
        Returns all cars registered for the current account

        :return: VehiclesResponse
        :rtype: VehiclesResponse
        """

        data = await self._api.get(self.url('/vehicles'))
        response = VehiclesResponse()
        response.parse(data)
        return response

    async def get_vehicle_data(self, vehicle: Vehicle):
        """
        Returns the vehicle data for the given vehicle

        :param vehicle: Vehicle with CSID
        :return: Vehicle data
        """
        return await self._api.get(self.url('/vehicle/{csid}'.format(csid=vehicle.csid)))

    def _get_path(self):
        return 'myaudi/carservice/v2'

class AudiLogonService(Service):
    """
    General API logon service
    """

    async def login(self, user: str, password: str, persist_token: bool = True):
        """
        Creates a new session using the given credentials

        :param user: User
        :param password: Password
        :param persist_token: True if the token should be persisted in the file system after login
        """
        token = await self.__login_request(user, password)
        self._api.use_token(token)
        if persist_token:
            token.persist()

    def restore_token(self):
        """
        Tries to restore the latest persisted auth token

        :return: True if token could be restored
        :rtype: bool
        """
        token = Token.load()
        if token is None or not token.valid():
            return False
        self._api.use_token(token)
        return True

    async def __login_request(self, user: str, password: str):
        """
        Requests a login token for the given user

        :param user: User
        :param password: Password
        :return: Token
        :rtype: Token
        """
        data = {'grant_type': 'password',
                'username': user,
                'password': password}
        reply = await self._api.post(self.url('/token'), data, use_json=False)
        return Token.parse(reply)

    def _get_path(self):
        return 'core/auth/v1'

class AudiVehicleStatusReportService(VehicleService):
    """
    General status of the vehicle
    """

    async def get_request_status(self, request_id: str):
        """
        Returns the status of the request with the given ID

        :param request_id: Request ID
        :return: RequestStatus
        :rtype: RequestStatus
        """
        data = await self._api.get(self.url('/vehicles/{vin}/requests/{request_id}/jobstatus', request_id=request_id))
        return RequestStatus(data)

    async def get_requested_current_vehicle_data(self, request_id: str):
        """
        Returns the vehicle report of the request with the given ID

        :param request_id: Request ID
        :return: VehicleDataResponse
        :rtype: VehicleDataResponse
        """
        data = await self._api.get(self.url('/vehicles/{vin}/requests/{request_id}/status', request_id=request_id))
        return VehicleDataResponse(data)

    async def request_current_vehicle_data(self):
        """
        Requests the latest report data from the vehicle

        :return: CurrentVehicleDataResponse
        :rtype: CurrentVehicleDataResponse
        """
        data = await self._api.post(self.url('/vehicles/{vin}/requests'))
        return CurrentVehicleDataResponse(data)

    async def get_stored_vehicle_data(self):
        """
        Returns the last vehicle data received

        :return: VehicleDataResponse
        :rtype: VehicleDataResponse
        """
        data = await self._api.get(self.url('/vehicles/{vin}/status'))
        return VehicleDataResponse(data)

    def _get_path(self):
        return 'bs/vsr/v1'
