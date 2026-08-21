# Cloudflare Access — SAML console walkthrough

Verified against Phase Two's [idp-wizard](https://github.com/p2-inc/idp-wizard)
(`Wizards/Providers/Cloudflare`).

## Before touching Cloudflare

Compute Keycloak's SP values (Entity ID, ACS URL). Cloudflare wants them before it hands back its
own metadata endpoint.

## Steps, in order

1. **Cloudflare Zero Trust dashboard** → Access controls → Applications → **Add an application** →
   type **SaaS** → enter a display name → authentication protocol **SAML** ("Select SAML") →
   Add Application.
2. Paste Keycloak's **Entity ID** and **Assertion Consumer Service URL** into the corresponding SP
   fields.
3. Copy Cloudflare's **"SAML Metadata endpoint"** value.
4. Call `createSamlIdp` with that endpoint as `metadataUrl`.
5. In **SAML attribute statements**, add statements for username, email, firstName, lastName — Name
   Format **"Unspecified"** for each — then **Save configuration**.
6. **Access Control → Policies**: create/assign a policy (name it, add groups/rules, assign to the
   app, Confirm).

## Attribute mapping (Keycloak side)

| Cloudflare attribute (Unspecified format) | Keycloak `userAttribute` |
|---|---|
| `username` | username |
| `email` | `email` |
| `firstName` | `firstName` |
| `lastName` | `lastName` |

## Gotchas

- Cloudflare passes attributes straight through from whatever identity provider is configured
  *inside* Cloudflare's own Zero Trust org. Its built-in one-time-PIN identity provider does **not**
  provide `firstName`/`lastName` at all — if those come back empty, the gap is upstream of Cloudflare
  and outside this wizard's scope (configuring an upstream IdP inside Cloudflare, via
  Integrations → Identity Providers, is a separate task).
- Use **"Unspecified"** name format, not "Basic" — Basic format needs an already-configured upstream
  identity provider to map attributes correctly.
