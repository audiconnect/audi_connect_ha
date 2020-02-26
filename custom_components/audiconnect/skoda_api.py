from .audi_api import AudiAPI

USERAGENT = "okhttp/3.7.0"
XCLIENTID = "28cd30c6-dee7-4529-a0e6-b1e07ff90b79"
XAPPVERSION = "3.1.6"
XAPPNAME = "cz.skodaauto.connect"


class SkodaAPI(AudiAPI):
    def __get_headers(self):
        data = {
            "User-Agent": USERAGENT,
            "X-App-Version": XAPPVERSION,
            "X-App-Name": XAPPNAME,
            "Accept": "application/json"
        }

        if self.__token != None:
            data["Authorization"] = "Bearer " + self.__token.get("access_token")

        return data
