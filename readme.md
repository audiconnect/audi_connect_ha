# Audi Connect for Home Assistant

[![GitHub Activity][commits-shield]][commits]
[![License][license-shield]](LICENSE)
[![HACS][hacsbadge]][hacs]

Connect your Audi to Home Assistant. See vehicle status, charging, climate, trips and other available features through native Home Assistant entities.

**Configure → Discover → Use.**

More vehicle coverage. Less configuration. Community-powered innovation.

> [!IMPORTANT]
> V2 remains the default and fallback. Experimental V3 is available only in builds that include it; it is not yet a stable release. See the [V3 review](https://github.com/audiconnect/audi_connect_ha/pull/918) and [V3 setup guide](docs/V3_REVIEW.md) before testing. See [V3 acceptance](docs/V3_FEATURE_CLOSURE.md) for current evidence and open release gates.

## What can it do?

Availability depends on your vehicle, market, permissions and installed runtime.

- **Vehicle status:** mileage, range, fuel, battery charge and last parked position.
- **Charging:** status, targets, profiles, timers and supported remote actions.
- **Climate:** temperature settings, auxiliary heating and supported controls.
- **Access:** doors, windows, lock state and supported lock/unlock actions.
- **Trips and service:** trip statistics, maintenance and oil information; persistent trip history in V3.
- **Diagnostics:** integration health, quota, data freshness and source evidence where available.

A successful cloud refresh does not mean the vehicle has sent new data. An accepted API request does not prove a physical action.

## Get started

1. Install Audi Connect through [HACS](https://hacs.xyz) using the supported release for your installation.
2. Restart Home Assistant.
3. Go to **Settings → Devices & Services → Add Integration → Audi Connect**.
4. Sign in with your Audi account, select your account region and use the normal polling interval (15 minutes by default, minimum 15). Supply the S-PIN only when needed for supported actions.

> [!IMPORTANT]
> Audi has changed its legacy login in affected regions. Where Home Assistant offers the interactive myAudi Auth0/PKCE login, open the displayed link in a private browser window, sign in and copy the complete redirected localhost callback URL into the Home Assistant form. An unable-to-connect page is expected. Never share this URL. See [authentication status #903](https://github.com/audiconnect/audi_connect_ha/issues/903).

Manual installation: copy the complete `custom_components/audiconnect/` directory from the intended release into your Home Assistant `custom_components/` directory and restart. Do not mix files from different versions.

Use **Configure** on the existing integration to adjust options. See the [V2 configuration and control reference](docs/V2_USER_GUIDE.md) for legacy API level, settings, services and dashboard examples.

## V3 — one vehicle, multiple sources

V3 is a capability-driven runtime within the same Audi Connect integration. It aims to adapt to different models, generations, regions and APIs without requiring model-specific code for every new field.

- Discover available capabilities and expose native Home Assistant entities.
- Consolidate observations from native Audi API families and optional, independently authorized EU Data Act data.
- Preserve existing device and entity identities and allow rollback to V2.
- Inspect data freshness, integration health and source evidence.

EU Data Act is read-only, optional and disabled by default. Its deliveries can be delayed by days; they never authorize or confirm a command. The optional administrator-only Engineering Workbench is for discovery and validation, not required for everyday use.

To try V3, back up Home Assistant, install a build that includes V3 and choose **V3 — Experimental** in the existing integration's options. Keep your existing config entry, devices and entities. See the [V3 guide](docs/V3_REVIEW.md) for Data Act setup, Workbench and rollback.

Field tests demonstrated persistent trip history and physical charging start/stop on a Q5 in B35, and Data Act delivery and consolidation on a Q8. Later Q5 builds reported charging STOP failures. These are vehicle-specific observations, not universal support. Manufacturer identity, charging reliability and cross-model acceptance remain open.

## Help us discover what your Audi can do

You do not need to be a Python developer. Every verified contribution can help other Audi owners.

- **Users:** report missing or incorrect data and compare it with your vehicle or myAudi.
- **Testers:** help validate different models, powertrains, regions and API generations.
- **Engineers:** use the optional Workbench to explore reviewed paths, inspect coverage, map fields, validate capabilities and share reusable definitions.

Start with the [contribution guide](CONTRIBUTING.md) or [open an issue](https://github.com/audiconnect/audi_connect_ha/issues/new/choose). We welcome ICE, PHEV and BEV vehicles, newer platforms such as PPE, older models and different markets.

> [!CAUTION]
> Use API calls and remote actions responsibly. Excessive requests may restrict your Audi account and affect the community. Do not repeatedly wake the vehicle, scan arbitrary endpoints or retry uncertain commands. Never post credentials, callback URLs, VINs, private locations, trips or raw responses.

## Documentation

- [V2 options, controls, services and dashboard example](docs/V2_USER_GUIDE.md)
- [V3 setup, Workbench and acceptance](docs/V3_REVIEW.md)
- [Contributing and sharing capabilities](CONTRIBUTING.md)
- [Engineering documentation and API research](docs/README.md)

## Credits and license

This integration builds on the outstanding work of @arjenvrh and the Audi Connect community. Thanks to the ioBroker VW-Connect community for initial API discovery and to davidgiga1993 for the original [AudiAPI](https://github.com/davidgiga1993/AudiAPI) implementation.

Licensed under the [MIT License](LICENSE). This is an unofficial community integration, not an Audi-supported API product.

[commits-shield]: https://img.shields.io/github/commit-activity/y/audiconnect/audi_connect_ha?style=for-the-badge
[commits]: https://github.com/audiconnect/audi_connect_ha/commits/master
[hacs]: https://github.com/custom-components/hacs
[hacsbadge]: https://img.shields.io/badge/HACS-Default-orange.svg?style=for-the-badge
[license-shield]: https://img.shields.io/github/license/audiconnect/audi_connect_ha?style=for-the-badge
