# Microsoft (social login, personal accounts) — console walkthrough

`providerId=microsoft`, driven by `createSocialIdp`. This is the **personal Microsoft account**
button. If the developer actually means a company's own Entra ID/Azure AD tenant (work or school
accounts), stop and use `admin:idp-federation`'s OIDC path (`createOidcIdp` with the tenant discovery
URL) instead — Keycloak's `microsoft` social provider's `tenantId` config can't even be set through
`createSocialIdp` (see "Known gaps" in `admin-social-login-mcp.md`), so this path can't be steered
to a single tenant anyway.

## Steps, in order

1. **Azure Portal → Microsoft Entra ID → App registrations → New registration.**
2. Under **"Supported account types,"** choose **"Personal Microsoft accounts only"** (this is what
   makes it the social/consumer provider rather than a tenant-scoped enterprise login).
3. Compute (or get from `createSocialIdp`'s return) the redirect URI:
   `{baseUrl}/realms/{deploymentRealm}/broker/{alias}/endpoint`. Add it under **Authentication → Add
   a platform → Web → Redirect URIs**, Save.
4. **Certificates & secrets → New client secret** — copy the secret value immediately (it's shown
   once).
5. Copy the **Application (client) ID** from the app's Overview page.
6. Call `createSocialIdp(providerId="microsoft", clientId=<application id>, clientSecret=<secret
   value>, ...)`.

## Gotchas

- The client secret is shown **once**, at creation time — if it's not copied then, the only fix is
  creating a new secret.
- Choosing "Accounts in this organizational directory only" or "Accounts in any organizational
  directory" at step 2 instead of "Personal Microsoft accounts only" produces a *work/school* login
  experience even though the tool is still called `createSocialIdp` — that's the wrong app
  registration type for this intent; redo step 2 if that happens.
