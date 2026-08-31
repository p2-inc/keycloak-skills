<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# Salesforce — OIDC and SAML console walkthroughs

Verified against Phase Two's [idp-wizard](https://github.com/p2-inc/idp-wizard)
(`Wizards/Providers/Salesforce`). Both protocol wizards share the same first step (create the
Connected App) before branching.

## Shared step 1 — create the Connected App

Salesforce Setup → **App Manager** (under Apps) → **New Connected App** → "Create a Connected App"
→ Continue → fill Basic Information (Connected App Name, API Name auto-populates, Contact Email).

## OIDC path

1. Under **"API (Enable OAuth Settings),"** check "Enable OAuth Settings"; select OAuth Scopes
   **"Access the identity URL service (id, profile, email, address, phone)"** and **"Access unique
   user identifiers (openid)"**; uncheck **"Require Proof Key for Code Exchange (PKCE)..."**; Save.
2. Retrieve the **Consumer Key**, **Consumer Secret**, and the org's **My Domain URL** (Setup →
   Company Settings → My Domain → "Current My Domain URL").
3. Call `createOidcIdp` with `issuerOrDiscoveryUrl = https://<my-domain>`, `clientId=Consumer Key`,
   `clientSecret=Consumer Secret`.
4. Paste the returned `redirectUri` into the Connected App's **"Callback URL"** field (under
   API/Enable OAuth Settings).

## SAML path

1. **Before** creating the Connected App: Setup → **Identity Provider** (under Identity) — verify
   Salesforce's own Identity Provider feature is enabled, or click **"Enable Identity Provider"**.
2. Create the Connected App (shared step 1).
3. Under **"Web App Settings,"** check **"Enable SAML,"** paste Keycloak's **Entity Id** into the
   Entity Id field and Keycloak's **ACS URL** into the ACS URL field, Save.
4. Copy the **"Metadata Discovery Endpoint"** URL from **"SAML Login Information."**
5. Call `createSamlIdp` with that URL as `metadataUrl`.
6. **Manage Profiles** — assign the connected app to the relevant profiles.
7. Add **Custom Attributes**: `firstName = $User.FirstName`, `lastName = $User.LastName`.

## Attribute mapping (Keycloak side)

| Salesforce source | Keycloak `userAttribute` |
|---|---|
| `$User.FirstName` | `firstName` |
| `$User.LastName` | `lastName` |
| (identity URL / SAML subject) | `email`, username per the standard identity claims |

## Gotchas

- OIDC: the PKCE-required checkbox must be **unchecked** — leave it checked and the token exchange
  Keycloak performs will fail.
- SAML: Salesforce's own Identity Provider feature has to be enabled **before** the Connected App
  step, not after — check step 1 first if anything in the SAML setup looks unavailable.
- SAML uses a metadata **URL** (Metadata Discovery Endpoint), unlike Oracle/PingOne/LastPass/Google,
  which hand back downloaded files — `metadataUrl` applies directly here.
