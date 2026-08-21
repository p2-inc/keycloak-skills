# Microsoft Entra ID (Azure AD) — SAML console walkthrough

Verified against Phase Two's own [idp-wizard](https://github.com/p2-inc/idp-wizard)
(`Wizards/Providers/MSFT_EntraID`). Prefer this SAML path when the developer wants an enterprise-app
style setup; if they'd rather use an app registration with a client secret, use `createOidcIdp`
against the tenant discovery URL instead (`connectingIdentityProvider`'s Stage 4 OIDC path covers
that shape) — both are valid, this file covers the SAML one.

## Before touching Entra ID

Compute Keycloak's SP values (see `admin-idp-federation-mcp.md`/`.md` Step 2) and have them ready —
Entra ID wants them *before* it will hand back its metadata.

## Steps, in order

1. **Entra ID (Azure) portal** → Enterprise applications → New application → "Create your own
   application" → enter an app name → choose **"Integrate any other application you don't find in
   the gallery (Non-gallery)"** → Create.
2. Open the app → **Single sign-on** (under Manage) → select **SAML**.
3. In **Basic SAML Configuration** (Edit icon), click "Add identifier" and paste Keycloak's
   **Entity ID**; click "Add reply URL" and paste Keycloak's **ACS URL**. Save.
4. Copy the **App Federation Metadata URL** from this same SAML setup page.
5. Call `createSamlIdp` (or the REST `import-config`) with that metadata URL as `metadataUrl` —
   Keycloak parses Entra's entity ID, SSO URL, and certificate from it.
6. Back in Entra ID, check **User Attributes & Claims**. If the default claims already match what
   you'll map (see below), skip this; otherwise edit each claim's namespace/source attribute to
   match: `.../claims/name`, `.../claims/emailaddress`, `.../claims/givenname`, `.../claims/surname`.
7. **Users and groups** → assign the users/groups who should get this app.

## Attribute mapping (Keycloak side)

The wizard maps these SAML attribute namespaces to Keycloak user attributes — use the same `source`
values in `addIdpAttributeMapper` — but see `admin-idp-federation-mcp.md`'s "known tool bug" note before trusting a success response from that tool; verify the mapper actually populates a field after a real login:

| Entra ID claim namespace | Keycloak `userAttribute` |
|---|---|
| `http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress` | `email` |
| `http://schemas.xmlsoap.org/ws/2005/05/identity/claims/givenname` | `firstName` |
| `http://schemas.xmlsoap.org/ws/2005/05/identity/claims/surname` | `lastName` |
| `http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name` | username |

## Gotchas

- If the default User Attributes & Claims already match the table above, don't edit them — the
  wizard step explicitly says editing is only needed when they differ.
- Step 6 requires editing each claim's *exact* namespace URI, not a display name — a typo here is
  the most common cause of an empty `email`/`firstName`/`lastName` after a successful login.
