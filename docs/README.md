# Engineering Documentation

The upstream [Audi Connect README](../readme.md) remains the authoritative user guide for installation, configuration and vehicle controls.

## V3 engineering and release

- [Architecture and ownership](V3_ARCHITECTURE_CLOSURE.md) — mandatory boundaries and maintainability gates.
- [Feature closure](V3_FEATURE_CLOSURE.md) — verified functionality, remaining OEM evidence and release blockers.
- [Upstream review](V3_REVIEW.md) — scope and source review.
- [V2 parity baseline](V2_V3_PARITY_BASELINE.json) — inventory, not proof of acceptance.

Review diagnostics against the installed runtime version before changing code.
Distinguish missing mappings, unavailable OEM data, invalid samples, historical
evidence and confirmed physical behavior. Reuse the existing owner and add a
focused regression test; do not add routes or polling to compensate for missing
evidence. Release candidates require exact-head CI and separate live acceptance.

## Research

- **[VW Group / CARIAD API research](research/cariad/README.md)** — canonical English research knowledge base, including the VW Group API evolution, cross-brand endpoint atlas, Audi/VW/Škoda/CUPRA/Porsche overlap, read-only and delayed EU Data Act feed, parked-vehicle data freshness, authentication/capabilities an adaptive multi-generation auth/API/vehicle/capability target architecture, NFR requirements, early experimental feature delivery and an engineering playbook.

This documentation is **research**, not an active deployment or a manufacturer-endorsed API contract. Do not assume unverified cross-brand endpoints work for Audi.
