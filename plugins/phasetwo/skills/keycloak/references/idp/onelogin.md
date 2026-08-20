# OneLogin — SAML console walkthrough

Verified against Phase Two's [idp-wizard](https://github.com/p2-inc/idp-wizard)
(`Wizards/Providers/OneLogin`).

## Steps, in order

1. **OneLogin Administration** → Applications → **Add App** → search **"SAML Custom Connector
   (Advanced)"** → select it → enter Display Name/Description → Save.
2. Under **Configuration**, paste Keycloak's **Entity ID** into "Audience (Entity ID)"; paste
   Keycloak's **ACS URL** into both **"Recipient"** and **"ACS URL"**; paste a regex-escaped version
   of the ACS URL (every `/` replaced with `\/`) into **"ACS URL Validator"**. Save.
3. Under **Parameters**, add mappings (see below), checking **"Include in SAML assertion"** for
   each.
4. (Optional) **Access** tab — access policy defaults to allowing all users if skipped.
5. Copy OneLogin's **Issuer URL** from the **SSO** section.
6. Call `createSamlIdp` with that URL as `metadataUrl`.

## Attribute mapping (Keycloak side)

| OneLogin parameter | Keycloak `userAttribute` |
|---|---|
| UUID → `id` | (the wizard also adds an extra mapper: Keycloak's `idpUserId` attribute ← `id`) |
| Username | username |
| Email | `email` |
| First name | `firstName` |
| Last name | `lastName` |

## Gotchas

- **"Include in SAML assertion"** must be checked for every parameter mapping, or that attribute
  never gets sent — a mapping that looks configured but wasn't checked silently sends nothing.
- The **ACS URL Validator** field wants the ACS URL with `/` escaped as `\/` — a plain unescaped
  paste there is a common source of a rejected assertion.
- Access policy is genuinely optional; don't treat its absence as a misconfiguration.
