# Contributing to Audi Connect

Help make Audi Connect easier to use and support more vehicles. Testing, translations, documentation, discovery and code contributions are equally welcome.

## Choose your contribution

- **Report a bug:** explain what is missing or incorrect, what you expected and how to reproduce it.
- **Test your vehicle:** compare Home Assistant data with the actual vehicle or myAudi. Report model, year, powertrain, region, versions and runtime.
- **Discover a capability:** share a new observed field, reviewed path or validated operation using the Capability discovery template.
- **Develop:** improve the shared registry, mappings, tests, translations or documentation.

Start at the [issue templates](https://github.com/audiconnect/audi_connect_ha/issues/new/choose).

## Explore with V3

V3 is experimental and opt-in. Use a backup or a separate test installation. Follow the [V3 guide](docs/V3_REVIEW.md); ordinary users do not need Workbench.

1. Enable the optional administrator-only Engineering Workbench in the integration options. Select your vehicle.
2. In **Overview**, inspect consolidated coverage. Where the source selector is available, choose an API family to investigate its own discovery, mapping and observation evidence. **API Log** shows retained operation evidence.
3. Use **Capabilities** and **Configure & test** to explore reviewed reads and propose a mapping. Use bounded read-only scans where applicable; respect quota and backoff. Discovery never runs physical commands.
4. Validate meaning, units, enum values, capture time and actual behavior against the vehicle or myAudi. Compare sources without assuming the newest delivery contains fresh data.
5. For supported custom definitions, use **Copy shareable definition** or the copy/paste JSON editor. A definition is not test evidence. Importing it does not execute or activate it.
6. Share the definition and sanitized evidence in a capability contribution. Maintainers can review the mapping, add regression tests and integrate it into the shared registry.

Only test reviewed remote actions on your own authorized vehicle, in a safe situation, with explicit intent. Never retry uncertain actions, invent success or use Data Act to authorize remote commands. Do not bypass authentication, permissions, host allowlists or request budgets.

## What to share

- **Context:** model, model year, powertrain, market, Home Assistant and integration versions, runtime (V2/V3).
- **Source:** API family, reviewed operation or relative path with VIN replaced by a placeholder.
- **Mapping:** field path or Data Act UUID and field name, type, unit, enum meanings, proposed canonical attribute.
- **Validation:** capture age, expected and actual state, and whether physically confirmed.
- **Definition:** reviewed portable JSON where available.

Do not post full HA diagnostics wrappers, raw HTTP responses, session cookies, passwords, S-PIN, OAuth URLs, tokens, VINs, private trips, locations or unrelated integration inventory. Check every attachment and screenshot. Use synthetic values in examples and tests.

## Contributing code

Use the existing project structure and [architecture and ownership contract](docs/V3_ARCHITECTURE_CLOSURE.md) for V3. Reuse the registry, canonical attributes, read/command owners and native HA projection. Prefer declarative mappings over model-specific conditions. Preserve existing entity identities, V2 behavior and rollback.

1. Fork the repository and branch from the target agreed with maintainers (normally `dev` for V3 work).
2. Make a focused change, add regression tests and update relevant documentation.
3. Run `pytest -q`, applicable Workbench tests and `pre-commit run --all-files`. Follow the existing workflows and semantic PR title conventions.
4. Open a pull request describing the change, evidence, compatibility and remaining live acceptance.

Keep documentation focused on product usage and technical knowledge. Use issues and pull requests for development progress, and release notes for user-visible changes.

Every improvement must preserve proven behavior and make the product simpler, more manageable, more efficient and more reliable. Keep experiments explicitly opt-in and isolated from proven functionality. Do not introduce a parallel framework, extra poller, duplicate entity or speculative command to compensate for missing evidence.

Contributions are licensed under the project's [MIT License](LICENSE).
