[![hacs][hacsbadge]](hacs)
![Project Maintenance][maintenance-shield]

## Configuration

Configuration is done through the Home Assistant UI.

To add the integration, go to **Settings ➤ Devices & Services ➤ Integrations**, click **➕ Add Integration**, and search for "Audi Connect".

![image](https://github.com/user-attachments/assets/68f4a38b-f09d-4486-a1a1-ab8a564095ab)

### Configuration Variables

**username**

- (string)(Required) The username associated with your Audi Connect account.

**password**

- (string)(Required) The password for your Audi Connect account.

**S-PIN**

- (string)(Optional) The S-PIN for your Audi Connect account.

**region**

- (Required) The region where your Audi Connect account is registered.
  - 'DE' for Europe (or leave unset)
  - 'US' for United States of America
  - 'CA' for Canada
  - 'CN' for China

**scan_interval**

- (number)(Optional) The frequency in minutes for how often to fetch status data from Audi Connect. (Optional. Default is 15 minutes, can be no more frequent than 15 min.)

**api_level**

- (number)(Required) For Audi vehicles, the API request data structure varies by model. Newer models use an updated structure, while older models use a legacy format. Setting the API level ensures that the system automatically applies the correct structure for each vehicle. You can update this setting later from the CONFIGURE menu if needed.
  - Level `0`: _Typically_ for gas vehicles
  - Level `1`: _Typically_ for e-tron (electric) vehicles.

[commits-shield]: https://img.shields.io/github/commit-activity/y/audiconnect/audi_connect_ha?style=for-the-badge
[commits]: https://github.com/audiconnect/audi_connect_ha/commits/master
[hacs]: https://github.com/custom-components/hacs
[hacsbadge]: https://img.shields.io/badge/HACS-Default-orange.svg?style=for-the-badge
[license-shield]: https://img.shields.io/github/license/arjenvrh/audi_connect_ha?style=for-the-badge
[maintenance-shield]: https://img.shields.io/badge/maintainer-audiconnect-blue.svg?style=for-the-badge
[blackbadge]: https://img.shields.io/badge/code%20style-black-000000.svg?style=for-the-badge
[black]: https://github.com/ambv/black
