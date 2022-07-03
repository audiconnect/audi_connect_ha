Audiconnect integration for home assistant
============================================================

[![GitHub Activity][commits-shield]][commits]
[![License][license-shield]](LICENSE.md)
[![Code Style][blackbadge]][black]

[![hacs][hacsbadge]](hacs)
![Project Maintenance][maintenance-shield]
[![BuyMeCoffee][buymecoffeebadge]][buymecoffee]

Description
------------
The `audiconnect` component offers integration with the Audi connect cloud service and offers presence detection, sensors such as range, mileage, and fuel level, and provides car actions such as locking/unlocking and setting the pre-heater.

Note that certain functions may require special permissions from Audi, such as the position update via GPS. 

Credits go to the guys at the ioBroker VW-Connect forum, which were able to figure out how the API and the pin hashing works, and to davidgiga1993 of the original [AudiAPI](https://github.com/davidgiga1993/AudiAPI) Python package on which some of this code is loosely based.

Installation
------------

There are two ways this integration can be installed into [Home Assistant](https://www.home-assistant.io).

The easiest way is to install the integration using [HACS](https://hacs.xyz).

Alternatively, installation can be done manually by copying the files in this repository into the custom_components directory in the HA configuration directory:
1. Open the configuration directory of your HA configuration.
2. If you do not have a custom_components directory, you need to create it.
3. In the custom_components directory create a new directory called audiconnect.
4. Copy all the files from the custom_components/audiconnect/ directory in this repository into the audiconnect directory.
5. Restart Home Assistant
6. Add the integration to Home Assistant (see `Configuration`)

Configuration
-------------

Configuration is done through the Home Assistant UI.

To add the integration, go to `Configuration->Integrations`, click `+` and search for `Audi Connect`

![Configuration](ha_config.png)

Configuration Variables
-----------------------
**username**

- (string)(Required)The username associated with your Audi Connect account.

**password**

- (string)(Required)The password for your given Audi Connect account.

**S-PIN**

- (string)(Optional)The S-PIN for your given Audi Connect account.

**region**

- (string)(Optional)The region where the Audi account is registered. Set to 'DE' for Europe (or leave unset), 'US' for United States of America, 'CA' for Canada, or 'CN' for China.

**scan_interval**

- specify in minutes how often to fetch status data from Audi Connect (optional, default 10 min, minimum 1 min)

Services
--------

**audiconnect.refresh_vehicle_data**

The normal update procedure retrieves the data from the servers and does not directly interact with the vehicle. This service triggers an update request from the vehicle. When the data is retrieved successfully, the data in Home Assistant is automatically updated. The service requires a vin as parameter. 

**audiconnect.execute_vehicle_action**

Executes a given action in the vehicle. The service takes a vin and an action as parameters. Possible action values:
- lock
- unlock 
- start_climatisation
- stop_climatisation
- start_charger
- start_timed_charger
- stop_charger
- start_preheater
- stop_preheater
- start_window_heating
- stop_window_heating 

Note that certain action require the S-PIN to be defined in the configuration. 

When the action was successfully performed, an update request from the vehicle is automatically triggered. 

Example Lovelace Card
---------------------

Below is an example Lovelace Card summarizing some of the sensors this Home Assistant addon provides. 

![Example Lovelace Card](card_example.png)

The card requires the following mods:
- https://github.com/thomasloven/lovelace-card-mod
- https://github.com/custom-cards/circle-sensor-card

which are obtainable via HACS.

The card uses the following code in ui-lovelace.yaml.
```yaml
     - type: picture-elements
        image: /local/pictures/audi_sq7.jpeg
        style: | 
          ha-card {
            border-radius: 10px;
            border: solid 1px rgba(100,100,100,0.3);
            box-shadow: 3px 3px rgba(0,0,0,0.4);
            overflow: hidden;
          } 
        elements:
        - type: image
          image: /local/pictures/cardbackK.png
          style:
            left: 50%
            top: 90%
            width: 100%
            height: 60px

        - type: icon
          icon: mdi:car-door
          entity: sensor.doors_trunk_sq7
          tap_action: more_info
          style: {color: white, left: 10%, top: 86%}
        - type: state-label
          entity: sensor.doors_trunk_sq7
          style: {color: white, left: 10%, top: 95%}

        - type: state-icon
          entity: sensor.windows_sq7
          tap_action: more_info
          style: {color: white, left: 30%, top: 86%}
        - type: state-label
          entity: sensor.windows_sq7
          style: {color: white, left: 30%, top: 95%}

        - type: icon
          icon: mdi:oil
          entity: sensor.audi_sq7_oil_level
          tap_action: more_info
          style: {color: white, left: 50%, top: 86%}
        - type: state-label
          entity: sensor.audi_sq7_oil_level
          style: {color: white, left: 50%, top: 95%}

        - type: icon
          icon: mdi:room-service-outline
          entity: sensor.audi_sq7_service_inspection_time
          tap_action: more_info
          style: {color: white, left: 70%, top: 86%}
        - type: state-label
          entity: sensor.audi_sq7_service_inspection_time
          style: {color: white, left: 70%, top: 95%}

        - type: icon
          icon: mdi:speedometer
          entity: sensor.audi_sq7_mileage
          tap_action: more_info
          style: {color: white, left: 90%, top: 86%}
        - type: state-label
          entity: sensor.audi_sq7_mileage
          style: {color: white, left: 90%, top: 95%}

        - type: custom:circle-sensor-card
          entity: sensor.audi_sq7_tank_level
          max: 100
          min: 0
          stroke_width: 15
          gradient: true
          fill: '#aaaaaabb'
          name: tank
          units: ' '
          font_style:
            font-size: 1.0em
            font-color: white
            text-shadow: '1px 1px black'
          style:
            top: 5%
            left: 80%
            width: 4em
            height: 4em
            transform: none

        - type: custom:circle-sensor-card
          entity: sensor.audi_sq7_range
          max: 630
          min: 0
          stroke_width: 15
          gradient: true
          fill: '#aaaaaabb'
          name: range
          units: ' '
          font_style:
            font-size: 1.0em
            font-color: white
            text-shadow: '1px 1px black'
          style:
            top: 5%
            left: 5%
            width: 4em
            height: 4em
            transform: none
```

[buymecoffee]: https://buymeacoff.ee/arjenvrh
[buymecoffeebadge]: https://img.shields.io/badge/buy%20me%20a%20beer-donate-yellow.svg?style=for-the-badge
[commits-shield]: https://img.shields.io/github/commit-activity/y/arjenvrh/audi_connect_ha?style=for-the-badge
[commits]: https://github.com/arjenvrh/audi_connect_ha/commits/master
[hacs]: https://github.com/custom-components/hacs
[hacsbadge]: https://img.shields.io/badge/HACS-Default-orange.svg?style=for-the-badge
[license-shield]: https://img.shields.io/github/license/arjenvrh/audi_connect_ha?style=for-the-badge
[maintenance-shield]: https://img.shields.io/badge/maintainer-Arjen%20van%20Rhijn%20%40arjenvrh-blue.svg?style=for-the-badge
[blackbadge]: https://img.shields.io/badge/code%20style-black-000000.svg?style=for-the-badge
[black]: https://github.com/ambv/black
