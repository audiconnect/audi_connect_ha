import uuid
from urllib.parse import urlparse, parse_qsl

import mechanize
from mechanize import BaseHandler

from .skoda_api import XAPPVERSION, XAPPNAME, USERAGENT, XCLIENTID
from .audi_models import Vehicle
from .audi_services import (AudiService)


class SkodaConnectUrlError(Exception):
    def __init__(self, _url):
        self.url = _url


class SkodaHandler(BaseHandler):
    handler_order = 1

    def http_error_302(self, req, fp, code, msg, headers):
        location = headers['location']
        if location.startswith('skodaconnect'):
            raise SkodaConnectUrlError(location)
        return


class SkodaVehicle(Vehicle):
    def __init__(self):
        super().__init__()
        self.vin = ''

    def parse(self, data):
        self.vin = data.get('content')

    def update(self, vehicle_data):
        data = vehicle_data.get('carportData')
        self.title = data.get('brand')
        self.model = data.get('modelName')
        self.model_year = data.get('modelYear')

    def __str__(self):
        return str(self.__dict__)


class SkodaVehiclesResponse:
    def __init__(self):
        self.vehicles = []

    def parse(self, data):
        response = data.get('userVehicles')
        for item in response.get('vehicle'):
            vehicle = SkodaVehicle()
            vehicle.parse(item)
            self.vehicles.append(vehicle)


class SkodaService(AudiService):
    TYPE = "Skoda"
    COMMON_HEADERS = {
        "User-Agent": USERAGENT,
        "X-App-Version": XAPPVERSION,
        "X-App-Name": XAPPNAME}

    async def get_vehicle_information(self):
        data = await self._api.get(
            "https://msg.volkswagen.de/fs-car/rolesrights/permissions/v1/Skoda/CZ/vehicles"
        )
        response = SkodaVehiclesResponse()
        response.parse(data)

        for vehicle in response.vehicles:
            vehicle_data = await self._api.get(
                "https://msg.volkswagen.de/fs-car/promoter/portfolio/v1/Skoda/CZ/vehicle/{vin}/carportdata".format(
                    vin=vehicle.vin)
            )
            vehicle.update(vehicle_data)

        return response

    async def login_request(self, user: str, password: str):
        self._api.use_token(None)

        browser = mechanize.Browser()
        browser.add_handler(SkodaHandler())

        browser.set_handle_robots(False)

        browser.open(
            "https://identity.vwgroup.io/oidc/v1/authorize?client_id={clientId}"
            "&scope={scope}&response_type={responseType}&redirect_uri={redirect}"
            "&nonce={nonce}&state={state}".format(
                nonce=uuid.uuid4().hex,
                state=uuid.uuid4().hex,
                type=self.TYPE,
                country=self._country,
                clientId="7f045eee-7003-4379-9968-9355ed2adb06@apps_vw-dilab_com",
                xclientId=XCLIENTID,
                scope="openid profile phone address cars email birthdate badge dealers driversLicense mbb",
                redirect="skodaconnect://oidc.login/",
                xrequest="cz.skodaauto.connect",
                responseType="code id_token",
                xappversion=XAPPVERSION,
                xappname=XAPPNAME))

        browser.select_form(nr=0)
        browser.set_value(id='input_email', value=user)
        browser.submit()
        browser.select_form(nr=0)
        browser.set_value(id='input_password_for_login', value=password)

        url = None
        try:
            browser.submit()
        except SkodaConnectUrlError as err:
            url = err.url

        values = urlparse(url)
        login_token = dict(parse_qsl(values.fragment))

        # Get VW Token
        data = {
            "grant_type": "id_token",
            "token": login_token.get("id_token"),
            "scope": "sc2:fal",
        }

        headers = {
            "X-Client-Id": XCLIENTID
        }

        headers.update(self.COMMON_HEADERS)

        self.vwToken = await self._api.request(
            "POST",
            "https://mbboauth-1d.prd.ece.vwg-connect.com/mbbcoauth/mobile/oauth2/v1/token",
            headers=headers,
            data=data,
        )

        self._api.use_token(self.vwToken)
