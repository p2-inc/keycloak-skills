<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# AWS IAM Identity Center — SAML console walkthrough

Verified against Phase Two's [idp-wizard](https://github.com/p2-inc/idp-wizard)
(`Wizards/Providers/AWS`).

## Before touching AWS

Compute Keycloak's SP values (Entity ID, ACS URL — see `admin-idp-federation-mcp.md`/`.md` Step 2).
AWS wants them entered manually before it will hand back its own metadata.

## Steps, in order

1. **AWS IAM Identity Center console** → Applications → **Add application** → **Add custom SAML 2.0
   application** → Next. Enter a Display Name/Description.
2. Use the **"you don't have a metadata file, manually type your metadata values"** link, and enter
   Keycloak's **ACS URL** into AWS's "ACS URL" field and Keycloak's **Entity ID** into "SAML
   audience."
3. Copy the **"IAM Identity Center SAML metadata file"** URL (click the box/copy icon next to it).
4. Call `createSamlIdp` with that URL as `metadataUrl`.
5. Back in AWS: Actions → **Edit attribute mappings** → add each mapping below with format
   **"unspecified"** → Save changes.
6. **Assign users** — groups are the preferred way to manage access here over individual users.

## Attribute mapping (Keycloak side)

| AWS attribute mapping (value → user) | Keycloak `userAttribute` |
|---|---|
| `Subject` → `${user:subject}` | username |
| `${user:email}` | `email` |
| `${user:givenName}` | `firstName` |
| `${user:familyName}` | `lastName` |

## Gotchas

- Every attribute mapping's format must be set to **"unspecified"** — AWS defaults to something
  else, and mismatched format is a common source of a broker login that authenticates but leaves
  Keycloak's user attributes blank.
- Click **"+ Add new attribute mapping"** per row and **Save changes** before moving on — nothing
  persists until that click.
