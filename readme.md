Audiconnect integration for home assistant
============================================================
Description
------------
The `audiconnect` component offers integration with the Audi connect cloud service and offers presence detection as well as sensors such as range, mileage, and fuel level.

Configuration
------------
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

- (string)(Optional)The region where the Audi is registered. Needs to be set for users in North America or China.

**name**

- (string)(Optional)Make it possible to provide a name for the vehicles. Note: Use all lower case letters when inputing your VIN number.

**resources**

- (list)(Optional)A list of resources to display (defaults to all available). Default value: false

**scan_interval**

- specify in minutes how often to fetch status data from carnet (optional, default 5 min, minimum 1 min)

**name**

- set a friendly name of your car you can use the name setting as in confiugration example.
