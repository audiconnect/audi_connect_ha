import sys
import asyncio
import getopt

from audiapi.Services import LockUnlockService, RemoteTripStatisticsService, RequestStatus

from audi_connect_account import AudiConnectAccount
from dashboard import Dashboard

def printHelp():
    print('test.py --user <username> --password <password>')


async def main(argv):
    user = ''
    password = ''
    try:
        opts, args = getopt.getopt(argv,"hu:p:",["user=","password="])
    except getopt.GetoptError:
        printHelp()
        sys.exit(2)
    for opt, arg in opts:
        if opt == '-h':
            printHelp()
            sys.exit()
        elif opt in ("-u", "--user"):
            user = arg
        elif opt in ("-p", "--password"):
            password = arg

    if (user == '' or password == ''):
        printHelp()
        sys.exit()

    account = AudiConnectAccount (user, password)
    await account.update()

    for vehicle in account.vehicles:

        dashboard = Dashboard(vehicle)
        for instrument in dashboard.instruments:
            print(str(instrument), instrument.str_state)

if __name__ == '__main__':
    task = main(sys.argv[1:])
    res = asyncio.get_event_loop().run_until_complete( task )
