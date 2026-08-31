<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# Facebook (social login) — console walkthrough

`providerId=facebook`, driven by `createSocialIdp`.

## Steps, in order

1. **Meta for Developers (developers.facebook.com) → My Apps → Create App.** Choose the
   **"Consumer"** (or "Authenticate and request data from users with Facebook Login") use case.
2. Add the **Facebook Login** product to the app.
3. Under **Facebook Login → Settings**, compute (or get from `createSocialIdp`'s return) the
   redirect URI: `{baseUrl}/realms/{deploymentRealm}/broker/{alias}/endpoint`, and add it to
   **"Valid OAuth Redirect URIs."**
4. Under **App settings → Basic**, copy the **App ID** and **App Secret** (click "Show" to reveal
   the secret).
5. Call `createSocialIdp(providerId="facebook", clientId=<App ID>, clientSecret=<App Secret>, ...)`.
6. While the app is in **Development mode**, only the app's own admins/developers/testers (added
   under **Roles**) can log in. Submitting the app for **App Review** (for the `public_profile`/
   `email` permissions) and switching it to **Live** is required before anyone else can use it.

## Attribute mapping (Keycloak side)

Keycloak's built-in Facebook mapper support (`fetchedFields`) controls which Graph API fields come
back at all — `createSocialIdp` doesn't expose it (see "Known gaps" in `admin-social-login-mcp.md`),
so the field set is whatever Facebook's default Graph API response includes for the requested
permissions. Map `email`, `first_name`, `last_name` with `addIdpAttributeMapper` if those permissions
were granted; don't assume they're present without checking a real login's claims. Also see
`admin-social-login-mcp.md`'s "known tool bug" note — verify the mapper actually populates a
field after a real login rather than trusting the tool's success response.

## Gotchas

- **Development mode blocks everyone except added testers** — this is the most common "it works for
  me but not for our users" report; check the app's mode before debugging anything else.
- Facebook's App Review process for `email`/`public_profile` can take real time; flag this as a
  vendor-side lead time, not something to work around in Keycloak.
