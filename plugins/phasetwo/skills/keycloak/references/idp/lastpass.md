# LastPass — SAML console walkthrough

Verified against Phase Two's [idp-wizard](https://github.com/p2-inc/idp-wizard)
(`Wizards/Providers/LastPass`).

## Steps, in order

1. **LastPass Admin Console** → Applications → search the catalog (or **Add app**) → search
   **"Custom service"** → select it → click **"Add new domain"** to create a new SAML connection.
2. Under **"Assign users and groups,"** give the application a Name and assign Users/Groups.
3. Paste Keycloak's **SP entity ID** and **ACS URL** into LastPass's corresponding "Service Provider
   entity ID" and "Assertion Consumer Service URL" fields.
4. Export/download LastPass's SAML metadata: click **"Export SAML Identity Provider Metadata"** →
   **Download**.
5. Call `createSamlIdp` with the explicit fallback fields read out of that downloaded file (LastPass
   hands back a file, not a URL).
6. Back in LastPass, add **Custom Attributes** mappings (see below), Save.

## Attribute mapping (Keycloak side)

The wizard hardcodes these three SAML attribute mappers on the Keycloak side after finishing:

| LastPass custom attribute | Keycloak `userAttribute` |
|---|---|
| `email` | `email` |
| `firstName` | `firstName` |
| `lastName` | `lastName` |

## Gotchas

- Each LastPass attribute mapping needs its own **"Add"** click, and the whole set needs a final
  **Save** — a mapping left unclicked doesn't persist even if the form looks filled in.
