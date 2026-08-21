# CyberArk (Identity) — SAML console walkthrough

Verified against Phase Two's [idp-wizard](https://github.com/p2-inc/idp-wizard)
(`Wizards/Providers/CyberArk`).

## Steps, in order

1. **CyberArk Identity Administration** → **Web Apps** → **Add Web Apps** → **Custom** tab → click
   **Add** next to the SAML app template → confirm **Yes** → close the dialog.
2. Give the app a **Name** and **Category**, Save.
3. On the app's **Trust** tab, under "Identity Provider Configuration," click **Copy URL** next to
   the URL field.
4. Call `createSamlIdp` with that URL as `metadataUrl`.
5. Back on the Trust page, switch **"Service Provider Configuration"** to **Manual Configuration** —
   this reveals the SP Entity ID and ACS URL fields. Paste Keycloak's **SP Entity ID** and **ACS
   URL** into them, then Save.
6. On the **SAML Response** page, add attribute mappings (see below).
7. On the **Permissions** page, **Add** and search for the users/groups/roles to assign, Save.

## Attribute mapping (Keycloak side)

| CyberArk SAML Response attribute | Keycloak `userAttribute` |
|---|---|
| `LoginUser.FirstName` | `firstName` |
| `LoginUser.LastName` | `lastName` |
| `LoginUser.Username` | username |
| `LoginUser.Email` | `email` |

## Gotchas

- The SP Entity ID/ACS URL fields on the Trust page are hidden until "Service Provider
  Configuration" is switched to **Manual Configuration** — easy to miss if only skimming the page.
