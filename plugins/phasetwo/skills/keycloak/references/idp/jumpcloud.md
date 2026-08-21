# JumpCloud — SAML console walkthrough

Verified against Phase Two's [idp-wizard](https://github.com/p2-inc/idp-wizard)
(`Wizards/Providers/JumpCloud`). **This is the one vendor in the family whose order is reversed** —
Keycloak's values go into JumpCloud *first*, and JumpCloud's metadata comes out *last*, after the
app is fully configured and activated. Don't apply the "compute Keycloak's SP values, get vendor
metadata, then create the IdP" pattern from the other vendor files here.

## Steps, in order

1. **JumpCloud console** → **SSO** → **"+"** to add an application → choose **"Custom SAML App"**
   (bottom of the app list). In **General Info**, enter a Display Label (and optional Description).
2. In the app's **SSO** tab, paste Keycloak's **IdP Entity ID**, **SP Entity ID** (same value as the
   IdP Entity ID), and **ACS URL** into JumpCloud's matching fields. Check **"Sign Assertion"**;
   leave everything else at defaults.
3. In **Attributes**, add mappings (see below) via **"add attribute"** under USER ATTRIBUTE MAPPING.
4. **User Groups** tab: assign groups, then click **activate** (confirm if prompted).
5. Back in the applications list, check the app and click **"export metadata"** — download the file.
6. Call `createSamlIdp` with the explicit fallback fields read out of that downloaded file (or, if
   you can host it, its contents as `metadataUrl`).

## Attribute mapping (Keycloak side)

| JumpCloud attribute | Keycloak `userAttribute` |
|---|---|
| `firstname` | `firstName` |
| `lastname` | `lastName` |
| `email` | `email` |

## Gotchas

- **Order is reversed** relative to every other vendor in this family — see the note above. If a
  step reflexively reaches for "get the vendor's metadata URL first," stop; JumpCloud doesn't work
  that way.
- The app must be **activated** (step 4) before exporting metadata (step 5) — exporting from an
  inactive app produces incomplete config.
