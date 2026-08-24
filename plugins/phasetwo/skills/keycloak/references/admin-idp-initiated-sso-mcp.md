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
| **Add IdP-initiated SSO to an EXISTING client** | `configureIdpInitiatedSso` | ✅ |
| **Target an OIDC/SPA client** (needs REDIRECT binding) | `configureIdpInitiatedSso(targetIsOidcClient=true, landingUrl=…)` | ✅ |

`createSamlClient` covers exactly one case: a **brand-new SAML** client. It always writes
`assertionConsumerServiceUrl` into `saml_assertion_consumer_url_post` and always sets
`protocol: saml`, and since a POST ACS URL outranks the redirect one in Keycloak's binding
priority, it can never produce the REDIRECT shape an OIDC target needs. For anything else — an
existing client of either protocol, or any OIDC/SPA target — use **`configureIdpInitiatedSso`**,
which reads the client's full representation and merges (Keycloak's client update is a
full-representation PUT that blanks whatever you omit).

### What an OIDC/SPA target actually gets — say this out loud

`targetIsOidcClient=true` is not "OIDC IdP-initiated SSO". Keycloak still builds and sends a real
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
| `saml.force.post.binding` | `forcePostBinding` | Must be `false` for an OIDC target — `createSamlClient` can't produce that; `configureIdpInitiatedSso(targetIsOidcClient=true)` sets it for you. |

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
*and* `forcePostBinding=false`; `createSamlClient` can't express that, which is what `configureIdpInitiatedSso(targetIsOidcClient=true)` exists to do — it clears both POST-forcing settings (`saml_assertion_consumer_url_post` and the client's `adminUrl`) and sets `saml.force.post.binding=false`.

## Steps — A. a brand-new SAML client

1. `whoAmI` — confirm caller and control-plane realm.
2. Confirm `deploymentId` + `deploymentRealm`, and the vendor IdP's `alias` via
   `listIdentityProviders`.
3. Agree a short, lowercase, whitespace-free `urlName` with the developer (e.g. `my-client`).
4. Call `createSamlClient` with `deploymentId`, `deploymentRealm`, the SP's `clientId` (entity ID)
   and `assertionConsumerServiceUrl` (or `spMetadataXml`), plus `idpInitiatedSsoUrlName` and
   `brokeredIdpAlias` = the vendor IdP alias. Echo the values back before calling.
5. Present the returned **`idpInitiatedSsoUrl`** prominently — that exact string is what goes into
   the vendor console. Because `brokeredIdpAlias` was passed, it will be the
   `/broker/{alias}/endpoint/clients/{urlName}` form.
6. Do the vendor-side configuration — read exactly one:
   `references/idp/okta-idp-initiated.md` or `references/idp/entra-idp-initiated.md`.

## Steps — B. an existing client (either protocol, including OIDC/SPA)

1. `whoAmI`; confirm `deploymentId` + `deploymentRealm`.
2. `listIdentityProviders` → confirm a `providerId: "saml"` entry for the vendor, note its `alias`.
3. `listClients` → confirm the target client exists, and note its `protocol`.
4. Agree the `urlName` with the developer. **One tile targets exactly one client** — routing is the
   `{urlName}` path segment alone, never RelayState — so a second client needs its own vendor-side
   tile.
5. `configureIdpInitiatedSso(deploymentId, deploymentRealm, clientId, urlName, …)`:
   - **SAML target** — that's all; POST binding is correct and expected.
   - **OIDC/SPA target** — also pass `targetIsOidcClient=true` and `landingUrl=<the app's own home
     URL>`. The tool clears `saml_assertion_consumer_url_post` and the client's `adminUrl` (either
     one would win and force POST) and sets `saml.force.post.binding=false`.
6. Hand the vendor the tile URL, built from the alias in step 2:
   `{base}/realms/{realm}/broker/{alias}/endpoint/clients/{urlName}`.
7. **For an OIDC target, state plainly what the developer is getting** — see "What an OIDC/SPA
   target actually gets" above. The tile click delivers no code and no token; the app still runs
   its own OIDC redirect, which then completes silently against the freshly-set SSO session.
8. Do the vendor-side configuration — read exactly one:
   `references/idp/okta-idp-initiated.md` or `references/idp/entra-idp-initiated.md`.

## Verify

`listClients` to confirm the client exists and is enabled. Then have the developer click the tile:
the user should land in the target app already authenticated, having never visited the app first.

## Re-running / fixing

A wrong `urlName`, or a target that turns out to be OIDC, is now a re-run of
`configureIdpInitiatedSso` with the corrected arguments — it merges into the client's existing
representation, so it is safe on a client already in use and does **not** need `deleteClient`.
Never delete and re-create a live client to fix an attribute.

Re-running is also the fix when the app receives a POST it can't handle: call it again with
`targetIsOidcClient=true` and the app's home URL as `landingUrl`.

## Common errors

- **"Client not found" / HTTP 400 at Keycloak** — the `{urlName}` in the vendor's ACS URL matches no
  client's `saml_idp_initiated_sso_url_name`, or that client is disabled.
- **"Wrong client protocol."** — the *direct* endpoint was used against an OIDC client; only the
  **broker** endpoint skips that check. Ensure `brokeredIdpAlias` was passed.
- **App gets a POST it can't handle** — POST binding won via case 1/2 or `forcePostBinding`. For an
  OIDC target this is the expected `createSamlClient` outcome — reconfigure with
  `configureIdpInitiatedSso(targetIsOidcClient=true)`, which targets the broker endpoint shape.
- **A second tile for a second client doesn't work** — expected; RelayState can't route. One
  vendor-side app per client.
