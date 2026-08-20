# Auth0 — OIDC and SAML console walkthroughs

Verified against Phase Two's [idp-wizard](https://github.com/p2-inc/idp-wizard)
(`Wizards/Providers/Auth0`). Both protocol wizards share the same first step (create the Auth0
application) before branching.

## Shared step 1 — create the application

Auth0 dashboard → **Applications** → **Create Application** → select **"Regular Web Applications"**.

## OIDC path

1. On the application's settings, note the **Domain**, **Client Id**, and **Client Secret**.
2. Call `createOidcIdp` with `issuerOrDiscoveryUrl = https://<domain>`, `clientId`, `clientSecret`.
3. Take the `redirectUri` it returns, and in Auth0's app settings under **Application URIs**, paste
   it into **Allowed Callback URLs** → Save Changes.

## SAML path

1. On the application, open the **Addons** tab → enable **"SAML2 WEB APP"**.
2. In the popup's **Usage** tab, download the **Identity Provider Metadata** file.
3. Read that file's contents (entity ID, SSO URL, certificate) and call `createSamlIdp` with the
   explicit fallback fields (`idpEntityId`, `singleSignOnServiceUrl`, `signingCertificate`) — Auth0
   hands back a file here, not a URL, so `metadataUrl` doesn't apply directly.
4. In the popup's **Settings** tab, paste Keycloak's **ACS URL** ("Application Callback URL") into
   the callback field, and paste this JSON snippet just below the final closing brace in the
   Settings JSON:
   ```json
   "logout": { "callback": "<Keycloak ACS URL>", "slo_enabled": true },
   ```
5. Scroll to the bottom and click **Enable** — easy to miss.

## Attribute mapping (Keycloak side)

Auth0's default OIDC claims and SAML attributes are the OIDC-standard ones — `email`, `given_name`,
`family_name` (OIDC) or their SAML-attribute equivalents. Map them the same way as the generic OIDC/
SAML instructions in `admin-idp-federation-mcp.md`/`.md` Step 4.

## Gotchas

- OIDC form requires Domain, Client Id, and Client Secret — all three, no partial validation.
- SAML: don't forget the **Enable** click at the very bottom of the popup after pasting settings —
  a completed-looking form that was never enabled produces no working login.
- SAML: the JSON snippet must go exactly "just below the final closing curly brace" of the existing
  Settings JSON — malformed JSON here breaks the addon silently.
