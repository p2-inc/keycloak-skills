# Google (social login) — console walkthrough

`providerId=google`, driven by `createSocialIdp`. This is the consumer "Sign in with Google" button
— **not** Google Workspace SAML (`references/idp/google-workspace.md`), which is enterprise
brokering for a company's own Workspace tenant.

## Steps, in order

1. Pick (or create) a project in the **Google Cloud Console**.
2. **APIs & Services → OAuth consent screen** — configure it first if this project hasn't already:
   choose **External** (or **Internal** if restricted to a Google Workspace org), fill in app name,
   support email, and the scopes this app will request (`email`, `profile`, `openid` cover the
   default `defaultScopes` Keycloak's social provider expects).
3. **APIs & Services → Credentials → Create Credentials → OAuth client ID** → application type
   **Web application**.
4. Call `createSocialIdp(providerId="google", ...)` first (or compute the redirect URI by hand:
   `{baseUrl}/realms/{deploymentRealm}/broker/{alias}/endpoint`) so you have the exact redirect URI
   to register — Google validates it exactly.
5. Paste that redirect URI into **"Authorized redirect URIs"** on the OAuth client, Save.
6. Copy the generated **Client ID** and **Client secret** back into `createSocialIdp`'s `clientId`/
   `clientSecret` (call it now if you deferred step 4, or re-create the IdP with `deleteIdentityProvider`
   + `createSocialIdp` if you already called it with placeholders).

## Gotchas

- If the OAuth consent screen is still in **"Testing"** mode, only the test users explicitly added
  can complete login — everyone else gets a Google-side "app not verified" block. Publishing the
  consent screen (or adding test users) is a Google-console action outside Keycloak's control; flag
  it if login works for the developer but not for anyone else.
- `hostedDomain` (restrict to one Workspace domain) is **not settable through `createSocialIdp`** —
  see `admin-social-login-mcp.md`'s "Known gaps" section for the workaround.
- Google's redirect-URI matching is exact — trailing slashes or `http` vs `https` mismatches are the
  most common cause of a redirect_uri_mismatch error.
