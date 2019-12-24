DOMAIN = 'audiconnect'

CONF_VIN = 'vin'
CONF_CARNAME = 'carname'
CONF_ACTION = 'action'

MIN_UPDATE_INTERVAL = 5
DEFAULT_UPDATE_INTERVAL = 10

CONF_SPIN = 'spin'
CONF_REGION = 'region'
CONF_SERVICE_URL = 'service_url'
CONF_MUTABLE = 'mutable'

SIGNAL_STATE_UPDATED = '{}.updated'.format(DOMAIN)
TRACKER_UPDATE = f"{DOMAIN}_tracker_update"

RESOURCES = [
     'position',
     'last_update_time',
     'mileage',
     'range',
     'service_inspection_time',
     'service_inspection_distance',
     'oil_change_time',
     'oil_change_distance',
     'oil_level',
     'charging_state',
     'max_charge_current',
     'engine_type1',
     'engine_type2',
     'parking_light',
     'any_window_open',
     'any_door_unlocked',
     'any_door_open',
     'trunk_unlocked',
     'trunk_open',
     'hood_open',
     'tank_level',
     'state_of_charge',
     'remaining_charging_time',
     'plug_state', 
     'sun_roof',
     'doors_trunk_status'
]

COMPONENTS = {
    'sensor': 'sensor',
    'binary_sensor': 'binary_sensor',
    'lock': 'lock',
    'device_tracker': 'device_tracker',
    'switch': 'switch',
}
