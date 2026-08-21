# Okta — IdP-initiated SSO tile console walkthrough

Vendor-side half of `admin:idp-initiated-sso`. Read the mechanics file first
(`admin-idp-initiated-sso-mcp.md` or `admin-idp-initiated-sso.md`) — the Keycloak-side settings and
the RelayState/binding rules live there and are not repeated here.

> **Scope note.** Okta's console layout and field names below reflect current general knowledge of
> the Okta admin experience; unlike the Keycloak-side behavior in the mechanics file (which is
> verified against Keycloak's source), it was **not** verified against Okta's own docs or a live
> tenant in this session. Have the developer confirm the field names against what's on their screen,
> and treat a mismatch as Okta having moved things, not as the recipe being wrong.

## Prerequisites

- Okta already brokered into the realm as a **SAML** identity provider (`admin:idp-federation`,
  SAML path) — note its **alias**.
- The target client already has its `saml_idp_initiated_sso_url_name` (`{urlName}`) set, and you
  have the resulting URL:
  ```
  {base}/realms/{realm}/broker/{oktaAlias}/endpoint/clients/{urlName}
  ```

## Steps, in order

1. **Okta Admin → Applications → Applications**, open the **SAML 2.0** app that backs this realm's
   Okta SAML identity provider. (If you're creating it fresh: Create App Integration → SAML 2.0.)
2. **General → SAML Settings → Edit.** Set:
   - **Single sign-on URL** = the `/clients/{urlName}` broker URL above. This replaces the plain
     broker ACS URL (`.../broker/{oktaAlias}/endpoint`) that ordinary SP-initiated federation uses.
     The `/clients/{urlName}` suffix is what makes Okta's unsolicited response land in one specific
     client.
   - **Audience URI (SP Entity ID)** = `{base}/realms/{realm}` — unchanged from the plain SAML IdP
     setup, unless a custom entity ID was set on the Keycloak IdP, in which case use that.
3. **Do not set "Default RelayState" expecting it to choose the client.** Per the verified behavior
   in the mechanics file, Keycloak discards the inbound RelayState entirely on this path. Leave it
   blank. If the developer already set it to a client ID, tell them it is inert and why.
4. **Advanced Settings**:
   - **Application username** — must produce whatever the Keycloak SAML IdP expects as NameID
     (matching the IdP's `nameIDPolicyFormat` / `principalType`). A mismatch here surfaces as a
     brokered user with the wrong or an empty username.
   - Leave **Enable Single Logout** off unless SLO has been configured on the Keycloak IdP
     separately — enabling it on one side only produces logout failures, not partial logout.
5. **Attribute statements** — whatever mappings the realm's IdP mappers expect. Unchanged from the
   ordinary SAML federation setup; IdP-initiated login doesn't alter claim handling.
6. **Assignments** — assign the app to the users/groups who should see the tile. The tile only
   appears for assigned users.
7. **Signing certificate** — Keycloak validates the assertion signature exactly as it does for
   SP-initiated login. If the IdP was created by importing Okta's metadata URL
   (`https://<okta-domain>/app/<app-id>/sso/saml/metadata`) the cert is already in place; nothing
   about IdP-initiated login relaxes signature validation.

## One tile, one client

Routing is by the `{urlName}` path segment only. If a second client needs its own tile, create a
**second Okta app** (or a second instance of it) whose Single sign-on URL carries that client's own
`{urlName}`. There is no per-tile Okta setting that can multiplex one app across several clients.

## Verify

Click the tile from the Okta end-user dashboard (Okta will prompt for Okta credentials first if
there's no Okta session — normal). The user should land in the target app already authenticated.

## Gotchas

- **Changing the Single sign-on URL breaks ordinary SP-initiated login through this same app** if
  anything relied on the plain `.../broker/{alias}/endpoint` ACS. If the realm needs both plain
  "log in with Okta" *and* a tile into one client, keep them as **separate Okta apps** rather than
  repointing the one that serves general federation.
- **App embed link vs dashboard tile** — Okta's app embed link works the same way; nothing extra to
  configure on the Keycloak side.
- Okta's own mandatory "customer feedback" step during app creation (choose "I'm an Okta customer
  adding an internal app", Finish, leave the extra form blank) is unrelated to this feature but
  blocks completing app creation.
