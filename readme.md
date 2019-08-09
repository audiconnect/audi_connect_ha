Audiconnect integration for home assistant
============================================================
Description
------------
The `audiconnect` component offers integration with the Audi connect cloud service and offers presence detection as well as sensors such as range, mileage, and fuel level.

Note that certain functions may require special permissions from Audi, such as the position update via GPS. 

Configuration
-------------
To use the `audiconnect` component in your installation, copy this repository into your home 
assistant configuration at `<config dir>/custom_components`.

Add the following to your `<config dir>/configuration.yaml` file.
```yaml
audiconnect:
    username: <username to audiconnect>
    password: <password to audiconnect>
    scan_interval: 
        minutes: 2
    name:
        wvw1234567812356: 'Audi Q7'
```

Configuration Variables
-----------------------
**username**

- (string)(Required)The username associated with your Audi Connect account.

**password**

- (string)(Required)The password for your given Audi Connect account.

**region**

- (string)(Optional)The region where the Audi account is registered. Set to 'DE' for Europe (or leave unset), set to 'US' for North America. May need to be set for China.

**name**

- (string)(Optional)Make it possible to provide a name for the vehicles. Note: Use all lower case letters when inputing your VIN number.

**resources**

- (list)(Optional)A list of resources to display (defaults to all available). Default value: false

**scan_interval**

- specify in minutes how often to fetch status data from Audi Connect (optional, default 10 min, minimum 1 min)

**name**

- set a friendly name of your car you can use the name setting as in confiugration example.

Services
--------

**refresh_vehicle_data**

The normal update procedure retrieves the data from the servers and does not directly interact with the vehicle. This service triggers an update request from the vehicle. When the data is retrieved successfully, the data in Home Assistant is automatically updated. The service requires a vin as parameter. 

Example Lovelace Card
---------------------

Below is an example Lovelace Card summarizing some of the sensors this Home Assistant addon provides. 

![Example Lovelace Card](https://raw.githubusercontent.com/arjenvrh/audi_connect_ha/master/card_example.png)

The card uses the following code in ui-lovelace.yaml.
```yaml
      - type: custom:card-modder
        style:
          border-radius: 20px
          border: solid 1px rgba(100,100,100,0.3)
          box-shadow: 3px 3px rgba(0,0,0,0.4)
          overflow: hidden
        card:          
          type: picture-elements
          image: /local/pictures/audi_sq7.jpeg
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
              entity: sensor.audi_sq7_doors_trunk_state
              tap_action: more_info
              style: {color: white, left: 10%, top: 86%}
            - type: state-label
              entity: sensor.audi_sq7_doors_trunk_state
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
                left: 85%
                width: 4em
                height: 4em
                transform: none

            - type: custom:circle-sensor-card
              entity: sensor.audi_sq7_range
              max: 650
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