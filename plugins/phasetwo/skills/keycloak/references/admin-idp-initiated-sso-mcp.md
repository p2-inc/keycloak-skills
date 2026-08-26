# IdP-initiated SSO into one client (Okta / Entra ID tile) — via the Keycloak MCP server

## What is being asked for

Normally the **app** starts the login (SP-initiated). **IdP-initiated** is the reverse: the user is
already in an external portal — an Okta dashboard tile, an Entra ID "My Apps" tile — clicks it, and
lands *inside one specific application*, already authenticated, with that app never having issued a
request.

This is a **narrow, advanced** capability. Don't route a plain "let our users log in with
Okta/Entra ID" request here — that's `admin:idp-federation` (ordinary SP-initiated brokering, one
login button serving every client). Only use this intent for a portal tile / app-embed link
targeting **one** downstream client.

## Read this first: which tool covers which case

| Purpose | Tool | Status |
|---|---|---|
| Identify caller / realm | `whoAmI` | ✅ |
| Confirm the vendor's SAML IdP exists, get its alias | `listIdentityProviders` | ✅ |
| Create a **new SAML** client with IdP-initiated SSO enabled | `createSamlClient` (`idpInitiatedSsoUrlName`, `idpInitiatedSsoRelayState`, `brokeredIdpAlias`, `forcePostBinding`) | ✅ |
| Confirm what exists | `listClients` | ✅ |
| Cleanup / re-create | `deleteClient` | ✅ |
| **Tile into an app that speaks SAML** | `createSamlClient` — POST binding, the default | ✅ |
| **Tile into an app that speaks OIDC (SPA)** | `createSamlClient` with `forcePostBinding=false` + a REDIRECT ACS | ✅ — one rough edge, below |
| Add a tile to an ALREADY-EXISTING client | *(none)* | ❌ narrow case → `admin-idp-initiated-sso.md` (rest) |

### The tile target is a SAML client in BOTH cases — including the OIDC one

This is the thing to get right before anything else, and it is not obvious:
**"the app speaks OIDC" does not mean the tile target is an OIDC client.** It isn't. In both
variants the client you create has `"protocol": "saml"`. What differs between them is two
attributes, nothing more:

| | App speaks SAML | App speaks OIDC (SPA) |
|---|---|---|
| `protocol` | `saml` | `saml` — *same* |
| `saml_idp_initiated_sso_url_name` | `myapp` | `myapp` — *same* |
| `saml.force.post.binding` | `true` | **`false`** |
| ACS attribute carrying the app's URL | `saml_assertion_consumer_url_post` | **`saml_assertion_consumer_url_redirect`** |
| `adminUrl` | unset | unset (must stay unset — it would force POST) |

So the tile target is a **dedicated SAML client whose only job is to be the tile**. For an OIDC
app, **you do not touch the SPA's real OIDC client at all** — it keeps its own client, its own
`redirectUris`, its own everything. The SAML client sits beside it purely to catch the tile click
and establish the SSO session.

That is why `createSamlClient` is the right tool for both, and why nothing here needs to modify an
existing client: a freshly created client has no `adminUrl` and no POST ACS unless you supply one,
so binding-priority cases 1 and 2 are naturally empty and the REDIRECT branch is reachable.

**The one rough edge:** `createSamlClient` has no direct parameter for
`saml_assertion_consumer_url_redirect` — its `assertionConsumerServiceUrl` argument always lands in
the **POST** attribute. The supported way to get the REDIRECT attribute set is the `spMetadataXml`
path: Keycloak's client-description-converter reads a `HTTP-Redirect`-binding
`AssertionConsumerService` out of SP metadata and writes it to
`saml_assertion_consumer_url_redirect` (verified in Keycloak's
`EntityDescriptorDescriptionConverter`). See Steps B. A single optional
`assertionConsumerServiceUrlRedirect` argument on `createSamlClient` would remove the need for the
metadata document — that's a one-parameter addition to the existing create tool, not a new tool.

### What an OIDC/SPA target actually gets — say this out loud

The OIDC variant is not "OIDC IdP-initiated SSO". Keycloak still builds and sends a real
SAML artifact to the landing URL, and an OIDC app cannot consume it — **the landing request hands
the app nothing: no code, no token.** What makes the experience work is that the Keycloak **SSO
session cookie is already set** by the time the browser arrives, so the app's own ordinary OIDC
redirect, issued a moment later, completes silently with no login prompt.

It is a **session-bootstrap trick, not a native OIDC IdP-initiated flow.** Tell the developer that
in those terms. Implying the tile click delivers tokens to the SPA is a materially different
security and architecture claim from what is actually happening, and it will shape how they build
the app's startup path.

## Two different endpoints — pick the right one first

Verified against Keycloak's source (`org.keycloak.protocol.saml.SamlService`,
`org.keycloak.broker.saml.SAMLEndpoint`):

| Who starts it | Endpoint | Client protocol allowed |
|---|---|---|
| **Keycloak itself** (a bookmark/portal link straight into Keycloak) | `{base}/realms/{realm}/protocol/saml/clients/{urlName}` | **SAML clients only** — `idpInitiatedSSO` calls `isClientProtocolCorrect()`, rejecting others with "Wrong client protocol." |
| **An external SAML IdP** (Okta/Entra tile) POSTing an unsolicited SAML response through Keycloak | `{base}/realms/{realm}/broker/{idpAlias}/endpoint/clients/{urlName}` | **any enabled client, including OIDC** — `SAMLEndpoint.samlIdpInitiatedSSO` filters only on `ClientModel::isEnabled`, with **no** protocol check |

That asymmetry is the reason an OIDC app can be a tile target at all. `createSamlClient`'s
`brokeredIdpAlias` argument is what switches the returned URL between these two shapes.

## Prerequisite: the vendor must already be brokered as a SAML IdP

Call `listIdentityProviders` and confirm a `providerId: "saml"` entry for Okta/Entra, noting its
`alias`. If it's missing, do `admin:idp-federation` first (SAML path — this mechanism is SAML-only;
there is no OIDC-broker equivalent for RelayState-chained IdP-initiated SSO).

## The settings that matter — all on the CLIENT, not the IdP

**A SAML identity provider has no IdP-initiated settings.** Verified by enumerating every getter on
`SAMLIdentityProviderConfig`: no "IDP Initiated SSO URL Name", no "IDP Initiated SSO Relay State".
Both are **client** attributes; the IdP contributes only its `alias` in the URL.

| Client attribute | `createSamlClient` arg | Role |
|---|---|---|
| `saml_idp_initiated_sso_url_name` | `idpInitiatedSsoUrlName` | **Mandatory.** The `{urlName}` segment; Keycloak resolves the target client by matching exactly this attribute. Omit ⇒ IdP-initiated login stays disabled. |
| `saml_idp_initiated_sso_relay_state` | `idpInitiatedSsoRelayState` | Optional **outgoing** RelayState handed to the downstream SP (a deep-link hint). Not routing — see below. |
| `saml.force.post.binding` | `forcePostBinding` | Leave default (`true`) for a SAML app. Must be **`false`** for an OIDC/SPA app, or it overrides the REDIRECT choice. |
| `saml_assertion_consumer_url_post` | `assertionConsumerServiceUrl` | The SAML app's ACS. **Leave unset for an OIDC app** — it wins binding priority and forces POST. |
| `saml_assertion_consumer_url_redirect` | *(no direct arg — via `spMetadataXml`)* | The OIDC/SPA app's landing URL. This is the rough edge noted above. |

### RelayState: what it does and does not do

On the broker path, `SAMLEndpoint.handleLoginResponse` takes the `{urlName}` branch and **never
reads the inbound `RelayState`** the vendor sent; `samlIdpInitiatedSSO` passes `null` on, so
`getOrCreateLoginSessionForIdpInitiatedSso` falls back to the client's own
`saml_idp_initiated_sso_relay_state` for the outgoing value. Therefore:

- **Okta's "Default RelayState" (or any vendor-side relay value) is discarded.** It is not the
  vendor-side twin of `idpInitiatedSsoRelayState`, and setting it to a client ID does nothing.
- **RelayState cannot select which client the user lands in.** Routing is entirely the `{urlName}`
  path segment — so **one vendor-side app/tile serves exactly one client**; a second client needs
  its own vendor-side app whose ACS/Reply URL bakes in that client's own `{urlName}`.

## Binding selection (for context, and what the OIDC switch actually changes)

`SamlService.getUrlAndBindingForIdpInitiatedSso`, strict priority:

1. `saml_assertion_consumer_url_post` → **POST**
2. else client `adminUrl` (*Master SAML Processing URL* — **not** "Home URL"/`baseUrl`) → **POST**
3. else `saml_assertion_consumer_url_redirect` → **REDIRECT** (GET)
4. else error (`INVALID_REDIRECT_URI`, "SAML assertion consumer url not set up")

And at response-build time `SamlProtocol.isPostBinding()` is
`POST.equals(clientNote(SAML_BINDING)) || samlClient.forcePostBinding()` — so `forcePostBinding=true`
silently overrides a REDIRECT choice. An OIDC target therefore needs case 3 with cases 1–2 unset
*and* `forcePostBinding=false`.

On a **freshly created** client that is mostly free: `createSamlClient` never sets `adminUrl`
(case 2 is empty by construction), and case 1 is empty as long as you don't pass
`assertionConsumerServiceUrl`. So the OIDC variant reduces to "supply a REDIRECT ACS, pass
`forcePostBinding=false`, and don't supply a POST ACS."

⚠️ **The trap on that path**: if you pass `spMetadataXml` *and* `assertionConsumerServiceUrl`, the
tool still writes the latter into `saml_assertion_consumer_url_post` (via `putIfAbsent`), case 1
wins, and the client silently POSTs despite `forcePostBinding=false`. For an OIDC target, pass the
metadata **only**.

## Steps common to both variants

1. `whoAmI` — confirm caller and control-plane realm.
2. Confirm `deploymentId` + `deploymentRealm`, and the vendor IdP's `alias` via
   `listIdentityProviders` (`providerId: "saml"`).
3. Agree a short, lowercase, whitespace-free `urlName` with the developer (e.g. `myapp`).
   **One tile targets exactly one client** — routing is the `{urlName}` path segment alone, never
   RelayState — so a second client needs its own vendor-side tile.
4. Ask which protocol **the end application** speaks. That is the only question that picks A vs B
   below; it does **not** change the client's own `protocol`, which is `saml` either way.

## Steps — A. the app speaks SAML

5. Call `createSamlClient` with `deploymentId`, `deploymentRealm`, the SP's `clientId` (entity ID)
   and `assertionConsumerServiceUrl` (or `spMetadataXml`), plus `idpInitiatedSsoUrlName` and
   `brokeredIdpAlias` = the vendor IdP alias. Echo the values back before calling.
   POST binding is correct and expected here — leave `forcePostBinding` alone.
6. Present the returned **`idpInitiatedSsoUrl`** prominently — that exact string is what goes into
   the vendor console. Because `brokeredIdpAlias` was passed, it will be the
   `/broker/{alias}/endpoint/clients/{urlName}` form.

## Steps — B. the app speaks OIDC (a SPA)

The SPA's **own OIDC client is not touched** — this creates a second, SAML client alongside it
whose only job is to catch the tile click.

5. Hand-author a minimal SP metadata document whose only `AssertionConsumerService` uses the
   **HTTP-Redirect** binding and points at the SPA's own home URL:
   ```xml
   <EntityDescriptor xmlns="urn:oasis:names:tc:SAML:2.0:metadata"
                     entityID="my-special-client">
     <SPSSODescriptor protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">
       <AssertionConsumerService
         Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"
         Location="https://my-oidc-special-client.example.com" index="0"/>
     </SPSSODescriptor>
   </EntityDescriptor>
   ```
6. Call `createSamlClient` with `spMetadataXml` = that document, `idpInitiatedSsoUrlName`,
   `brokeredIdpAlias`, and **`forcePostBinding=false`**. Do **not** also pass
   `assertionConsumerServiceUrl` — see the trap above; it would force POST.
7. `listClients` and confirm the created client's attributes actually match the OIDC column of the
   table at the top: `saml.force.post.binding=false`, `saml_assertion_consumer_url_redirect` set,
   `saml_assertion_consumer_url_post` absent/empty, `adminUrl` absent/empty. Don't skip this —
   every failure mode on this path is a silent fallback to POST.
8. **State plainly what the developer is getting** — see "What an OIDC/SPA target actually gets"
   above. The tile click delivers no code and no token; the SPA still runs its own OIDC redirect,
   which then completes silently against the freshly-set SSO session.

## Then, for both: the vendor console

9. Hand the vendor the tile URL: `{base}/realms/{realm}/broker/{alias}/endpoint/clients/{urlName}`,
   and read exactly one of `references/idp/okta-idp-initiated.md` or
   `references/idp/entra-idp-initiated.md`.

**The vendor side is identical for A and B, and identical between Okta and Entra ID.** The vendor
always POSTs an unsolicited SAML response to that same broker URL; POST-vs-REDIRECT is purely
about the *second* hop (Keycloak → the app) and is invisible to the IdP. Nothing in either vendor
walkthrough changes based on which variant you built.

## Adding a tile to an already-existing client

Narrow case, and the only one with no MCP path: a client that already exists and merely lacks
`saml_idp_initiated_sso_url_name`. There is no update-client tool — switch to
`admin-idp-initiated-sso.md` (rest) for a read-merge-PUT. Don't `deleteClient` and re-create a
live client to add an attribute. Note this is **not** the OIDC case: for a SPA you create a new
SAML client (Steps B) rather than modifying the SPA's existing OIDC one.

## Verify

`listClients` to confirm the client exists and is enabled. Then have the developer click the tile:
the user should land in the target app already authenticated, having never visited the app first.

## Re-running / fixing

The tile client created here is a **dedicated shim, not the app's real client**, so it is cheap to
throw away: `deleteClient` + `createSamlClient` with corrected arguments is a legitimate fix for a
wrong `urlName` or a variant built the wrong way round. That is safe *specifically because* nothing
else depends on this client — do not generalize it to the app's real OIDC/SAML client, which must
never be deleted to fix an attribute.

If the client must be preserved (it is the app's real SAML client, not a shim), switch to
`admin-idp-initiated-sso.md`'s read-merge-PUT instead.

## Common errors

- **"Client not found" / HTTP 400 at Keycloak** — the `{urlName}` in the vendor's ACS URL matches no
  client's `saml_idp_initiated_sso_url_name`, or that client is disabled.
- **"Wrong client protocol."** — the *direct* endpoint was used against an OIDC client; only the
  **broker** endpoint skips that check. Ensure `brokeredIdpAlias` was passed.
- **SPA gets a POST it can't handle** — POST binding won via priority case 1 or 2, or
  `forcePostBinding` was left at its `true` default. Almost always one of: `assertionConsumerServiceUrl`
  was passed alongside `spMetadataXml`, or the metadata's ACS used the POST binding rather than
  HTTP-Redirect. Check the four attributes in the OIDC column of the table at the top.
- **A second tile for a second client doesn't work** — expected; RelayState can't route. One
  vendor-side app per client.
