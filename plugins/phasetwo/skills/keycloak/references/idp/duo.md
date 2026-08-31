<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# Duo (SSO) — SAML console walkthrough

Verified against Phase Two's [idp-wizard](https://github.com/p2-inc/idp-wizard)
(`Wizards/Providers/Duo`).

## Steps, in order

1. **Duo Security admin app** → Applications → **Protect an Application** → search
   **"Generic Service Provider"** → click **Protect**.
2. Copy the app's **Metadata URL** link.
3. Call `createSamlIdp` with that URL as `metadataUrl`.
4. Back in Duo, submit Keycloak's **Entity ID** and **ACS URL** into the app's SP fields (the
   wizard's own step text doesn't name Duo's exact field labels beyond "submit the Entity ID and the
   ACS URL" — expect something like "Entity ID" / "ACS URL" or "Reply URL" on Duo's SAML Response
   section; confirm against what's on screen rather than assuming an exact label).
5. In Duo's **SAML Response** section, add attribute mappings via the **"Map attributes"** (+)
   button (see below).
6. In **Settings**, name the application, scroll to the bottom, and **Save**.

## Attribute mapping (Keycloak side)

| Duo attribute | Keycloak `userAttribute` |
|---|---|
| Username → `id` | username |
| Email address → `email` | `email` |
| First Name → `firstName` | `firstName` |
| Last Name → `lastName` | `lastName` |

## Gotchas

- Duo's own wizard step text is less explicit than most other vendors about exact field names for
  Entity ID/ACS URL — treat that step as "find the equivalent SP-configuration fields on Duo's app
  page" rather than a literal label match.
