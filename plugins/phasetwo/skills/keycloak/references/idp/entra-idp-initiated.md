# Microsoft Entra ID (Azure AD) — IdP-initiated SSO tile console walkthrough

Vendor-side half of `admin:idp-initiated-sso`. Read the mechanics file first
(`admin-idp-initiated-sso-mcp.md` or `admin-idp-initiated-sso.md`) — the Keycloak-side settings and
the RelayState/binding rules live there and are not repeated here.

> **Scope note.** The Entra ID console layout and field names below reflect current general
> knowledge of the Azure portal; unlike the Keycloak-side behavior in the mechanics file (verified
> against Keycloak's source), they were **not** verified against Microsoft's docs or a live tenant in
> this session. Have the developer confirm against what's on their screen, and treat a mismatch as
> Microsoft having moved things rather than the recipe being wrong.

## Prerequisites

- Entra ID already brokered into the realm as a **SAML** identity provider
  (`admin:idp-federation`, SAML path — see also `references/idp/entra-id.md` for that setup) — note
  its **alias**.
- The target client already has its `saml_idp_initiated_sso_url_name` (`{urlName}`) set, and you
  have the resulting URL:
  ```
  {base}/realms/{realm}/broker/{entraAlias}/endpoint/clients/{urlName}
  ```

## Steps, in order

1. **Azure Portal → Microsoft Entra ID → Enterprise applications**, open the **non-gallery / custom**
   app that backs this realm's Entra SAML identity provider. (Creating fresh: New application →
   Create your own application → "Integrate any other application you don't find in the gallery
   (Non-gallery)".)
2. **Single sign-on → SAML → Basic SAML Configuration** (Edit):
   - **Identifier (Entity ID)** = Keycloak's broker SP entity ID, i.e. `{base}/realms/{realm}`
     (or the custom entity ID set on the Keycloak IdP). Unchanged from the plain SAML federation
     setup.
   - **Reply URL (Assertion Consumer Service URL)** = the `/clients/{urlName}` broker URL above.
     This suffix is what makes Entra's unsolicited response land in one specific client, instead of
     the plain `.../broker/{entraAlias}/endpoint` used for ordinary SP-initiated federation.
   - **Sign on URL** = leave **blank**. A populated Sign on URL is what makes the My Apps tile
     perform *SP-initiated* login (sending the user to the app first); leaving it empty is what
     makes the tile emit an unsolicited SAML response instead. This is the field that switches the
     tile's behavior — flag it as the one most likely to be wrong if the tile "works" but goes
     through the app rather than straight in.
   - Save.
3. **There is no Entra field that selects which client to land in** beyond the Reply URL itself.
   Per the verified behavior in the mechanics file, any RelayState Entra attaches is discarded on
   this path. Don't go looking for (or invent) an Entra twin of Okta's "Default RelayState" — and if
   the developer's notes say to set one, it's inert.
4. **Users and groups** — assign the users/groups who should see the My Apps tile.
5. **Attributes & Claims** — whatever the realm's IdP mappers expect; unchanged from the ordinary
   SAML federation setup (see `references/idp/entra-id.md` for the claim namespaces). IdP-initiated
   login doesn't alter claim handling.
6. **Signing certificate** — Keycloak validates the assertion signature exactly as for SP-initiated
   login. If the IdP was created by importing Entra's *App Federation Metadata Url*, the cert is
   already in place; nothing here relaxes signature validation. Watch the Entra certificate's
   expiry — a rollover breaks the tile and ordinary federation together.

## One tile, one client

Routing is by the `{urlName}` path segment only. A second client needs its **own enterprise
application** registration in Entra (or its own instance), with a Reply URL carrying that client's
own `{urlName}`. One app cannot multiplex across clients.

## Verify

Open the tile from **My Apps** (`myapplications.microsoft.com`). The user should land in the target
app already authenticated, having never visited the app first.

## Gotchas

- **Repointing the Reply URL breaks ordinary SP-initiated login through this same app** if anything
  relied on the plain `.../broker/{alias}/endpoint` ACS. If the realm needs both plain "log in with
  Entra ID" *and* a tile into one client, keep them as **separate enterprise applications**. (Entra
  does allow multiple Reply URLs on one app, but only one can be the default for an unsolicited
  response — don't rely on multi-URL to serve both purposes from one app.)
- **Entra may reject a Reply URL it considers malformed** — if the save fails, confirm the URL is
  absolute, https where required by the tenant's policy, and that it was actually saved rather than
  just typed into the form.
- **Tile lands on a Microsoft error rather than Keycloak** — usually the Reply URL wasn't saved with
  the `/clients/{urlName}` suffix, or the user isn't assigned to the app.
