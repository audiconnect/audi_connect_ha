import sys
import asyncio
import getopt
import time

from audiapi.Services import (
    LockUnlockService,
    RemoteTripStatisticsService,
    RequestStatus,
)

from audiconnect.audi_connect_account import AudiConnectAccount
from audiconnect.dashboard import Dashboard

from aiohttp import ClientSession

def printHelp():
    print("test.py --user <username> --password <password> --spin <spin>")

async def main(argv):
    user = ""
    password = ""
    spin = ""
    try:
        opts, _ = getopt.getopt(argv, "hu:p:s:", ["user=", "password=", "spin="])
    except getopt.GetoptError:
        printHelp()
        sys.exit(2)
    for opt, arg in opts:
        if opt == "-h":
            printHelp()
            sys.exit()
        elif opt in ("-u", "--user"):
            user = arg
        elif opt in ("-p", "--password"):
            password = arg
        elif opt in ("-s", "--spin"):
            spin = arg

    if user == "" or password == "":
        printHelp()
        sys.exit()

    async with ClientSession() as session:
        account = AudiConnectAccount(session, user, password, "DE", spin)

        await account.update(None)

        for vehicle in account._vehicles:

            dashboard = Dashboard(account, vehicle, miles=True)
            for instrument in dashboard.instruments:
                print(str(instrument), instrument.str_state)


if __name__ == "__main__":
    task = main(sys.argv[1:])
    res = asyncio.get_event_loop().run_until_complete(task)
