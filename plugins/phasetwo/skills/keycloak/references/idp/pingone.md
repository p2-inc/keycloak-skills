# PingOne — SAML console walkthrough

Verified against Phase Two's [idp-wizard](https://github.com/p2-inc/idp-wizard)
(`Wizards/Providers/PingOne`).

## Steps, in order

1. **PingOne Admin dashboard** → Connections → Applications → **"+"** → enter Application Name and
   Description → select **"SAML Application"** → Configure.
2. Choose **"Manually Enter"** and paste Keycloak's **ACS URL** into "ACS URL" and Keycloak's
   **Entity ID** into "Entity ID." Save.
3. Configure **Attribute Mappings**: edit the existing default `saml_subject` outgoing mapping to
   use **"Username"** (User ID / `saml_subject`), then add the mappings below.
4. (Optional) **Access** tab — restrict to specific groups; default allows all groups.
5. **Enable** the application, then **Download Metadata**.
6. Call `createSamlIdp` with that downloaded file's contents via the explicit fallback fields.

## Attribute mapping (Keycloak side)

| PingOne mapping | Keycloak `userAttribute` |
|---|---|
| `saml_subject` ← Username (edited default) | username |
| Username | (also mapped as above) |
| Email Address | `email` |
| Given name | `firstName` |
| Family name | `lastName` |

## Gotchas

- The default `saml_subject` mapping **exists already** but outputs the wrong thing until you edit
  it — adding a new mapping alongside it isn't enough; the existing one must be changed to output
  "Username."
- Group restriction is optional; the PingOne default is to allow every group.
