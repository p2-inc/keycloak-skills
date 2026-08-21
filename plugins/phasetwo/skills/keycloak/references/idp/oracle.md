# Oracle (OCI IAM) — SAML console walkthrough

Verified against Phase Two's [idp-wizard](https://github.com/p2-inc/idp-wizard)
(`Wizards/Providers/Oracle`).

## Steps, in order

1. **OCI Console** → Identity & Security → **Domains** → pick the target domain → **Integrated
   Applications** → **Add application** → **"SAML Application"** → Launch Workflow. Enter a Name →
   Next.
2. Download Oracle's **identity provider metadata** (button on this step).
3. Call `createSamlIdp` with the explicit fallback fields read out of that file (Oracle hands back a
   file, not a URL).
4. In the app's **General** section, paste Keycloak's **Entity ID** into "Entity ID" and Keycloak's
   **ACS URL** into "Assertion consumer URL." In **Additional configurations**, uncheck
   **"Enable single logout."**
5. In **Attribute configuration**, add four mappings via **"+ Additional attribute"** (see below).
6. **Finish/Activate** the app, then assign Groups or Users for access.

## Attribute mapping (Keycloak side)

| Oracle attribute name / type | Keycloak `userAttribute` |
|---|---|
| `firstName` / First name | `firstName` |
| `lastName` / Last name | `lastName` |
| `email` / Primary email | `email` |
| `username` / User Name | username |

## Gotchas

- If IdP creation fails on the Keycloak side, first check there isn't already an Oracle Cloud SAML
  IdP configured for this deployment (a wizard-internal note, not something Oracle's own UI warns
  about).
- Single logout gets explicitly disabled in step 4 — don't re-enable it without checking whether
  Keycloak's SLO endpoint is actually wired up for this IdP.
