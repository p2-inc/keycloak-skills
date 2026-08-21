---
name: idpInitiatedSsoMcp
description: >-
  Wire IdP-initiated SSO ("portal tiles") from an already-federated SAML identity provider
  such as Okta or Microsoft Entra ID into ONE specific Keycloak client, when the Keycloak
  MCP server is available. Use this whenever someone asks for an Okta dashboard tile or an
  Entra "My Apps" tile that drops the user straight inside a particular application already
  logged in, for an app-embed link, or for "IdP-initiated SSO" / "unsolicited SAML response"
  into a named client. Covers which MCP tools help (whoAmI, listIdentityProviders,
  listClients, createSamlClient) and - critically - the two things the MCP surface cannot do
  here at all: add IdP-initiated SSO to an EXISTING client, and target an OIDC client. Both
  need raw Admin REST, so recognise the gap and drop to REST instead of thrashing with
  create/delete cycles. Not plain "let our users log in with Okta/Entra" federation - that
  is ordinary SP-initiated brokering, one login button serving every client.
---

# IdP-initiated SSO into one client (Okta / Entra tile) — with the Keycloak MCP server

## What this is, and what it is NOT

Normally the **app** starts the login (SP-initiated). **IdP-initiated** is the reverse: the
user is already in an external portal — an Okta dashboard tile, an Entra ID "My Apps" tile —
clicks it, and lands *inside one specific application*, already authenticated, with that app
never having issued a request.

A plain "let our users log in with Okta/Entra" request is ordinary SP-initiated brokering
(one login button serving every client) — not this. Use this only for a portal tile /
app-embed link targeting **one** downstream client.

## Read this first: what the MCP surface can and cannot do here

| Purpose | Tool | Status |
|---|---|---|
| Identify caller / realm | `whoAmI` | ✅ |
| Confirm the vendor's SAML IdP exists, get its alias | `listIdentityProviders` | ✅ |
| Confirm what clients exist and what they look like | `listClients` | ✅ |
| Create a **new SAML** client with IdP-initiated SSO enabled | `createSamlClient` (`idpInitiatedSsoUrlName`, `idpInitiatedSsoRelayState`, `brokeredIdpAlias`, `forcePostBinding`) | ✅ |
| Cleanup / re-create | `deleteClient` | ✅ |
| **Add IdP-initiated SSO to an EXISTING client** | — | ❌ **no tool** |
| **Target an OIDC client** (needs REDIRECT-binding attributes) | — | ❌ **not possible** |

Both gaps are real and verified against the server source (`ClientTools.java`), not guesses:

- The only client-mutating tools are `createOidcClient`, `createSamlClient`, `deleteClient`,
  `setClientLoginTheme`, `clearClientLoginTheme`. There is **no update-client tool**, so
  IdP-initiated SSO can only be set at **creation** time, on a **new** client.
- `createSamlClient` always writes `assertionConsumerServiceUrl` into
  `saml_assertion_consumer_url_post` (and requires either that or `spMetadataXml`), and
  always sets `protocol: saml`. Since a POST ACS URL outranks the redirect one in Keycloak's
  binding priority, the tool **cannot** produce the REDIRECT-binding configuration an OIDC
  target requires.

**So: if the target is an existing client, or an OIDC client, say so plainly and switch to
raw Admin REST.** Do not delete and re-create an existing, in-use client to work around the
missing update tool, and do not loop on create/delete hoping a different argument
combination will produce a REDIRECT binding — it cannot. Tell the developer which path
you're on and why; don't quietly hand-roll REST while claiming to be driving MCP tools.

## Two different endpoints — pick the right one first

Verified against Keycloak's source (`org.keycloak.protocol.saml.SamlService`,
`org.keycloak.broker.saml.SAMLEndpoint`):

| Who starts it | Endpoint | Client protocol allowed |
|---|---|---|
| **Keycloak itself** (a bookmark/portal link straight into Keycloak) | `{base}/realms/{realm}/protocol/saml/clients/{urlName}` | **SAML clients only** — `idpInitiatedSSO` calls `isClientProtocolCorrect()`, rejecting others with HTTP 400 "Wrong client protocol." |
| **An external SAML IdP** (Okta/Entra tile) POSTing an unsolicited SAML response through Keycloak | `{base}/realms/{realm}/broker/{alias}/endpoint/clients/{urlName}` | **any enabled client, including OIDC** — `SAMLEndpoint.samlIdpInitiatedSSO` filters only on `ClientModel::isEnabled`, with **no** protocol check |

That asymmetry is the reason an OIDC app can be a tile target at all.
`createSamlClient`'s `brokeredIdpAlias` argument is what switches the returned
`idpInitiatedSsoUrl` between these two shapes.

The vendor must already be brokered as a **SAML** identity provider — call
`listIdentityProviders` and note the `providerId: "saml"` entry's `alias`. This mechanism is
SAML-only; there is no OIDC-broker equivalent.

## The settings that matter — all on the CLIENT, not the identity provider

**A SAML identity provider has no IdP-initiated settings.** Verified by enumerating every
getter on `SAMLIdentityProviderConfig`: no "IDP Initiated SSO URL Name", no "IDP Initiated
SSO Relay State". Both are **client** attributes; the provider contributes only its `alias`
in the URL. The request arrives phrased entirely in terms of Okta and Entra, so the identity
provider is where everyone looks first — nothing goes there.

| Client attribute | `createSamlClient` arg | Role |
|---|---|---|
| `saml_idp_initiated_sso_url_name` | `idpInitiatedSsoUrlName` | **Mandatory.** The `{urlName}` segment; Keycloak resolves the target client by matching exactly this attribute. Omit ⇒ IdP-initiated login stays disabled. |
| `saml_idp_initiated_sso_relay_state` | `idpInitiatedSsoRelayState` | Optional **outgoing** RelayState handed to the downstream SP (a deep-link hint). Not routing — see below. |
| `saml.force.post.binding` | `forcePostBinding` | Must be `false` for an OIDC target (which this tool can't produce anyway). |

### RelayState: what it does and does not do

On the broker path, `SAMLEndpoint.handleLoginResponse` takes the `{urlName}` branch and
**never reads the inbound `RelayState`** the vendor sent; `samlIdpInitiatedSSO` passes `null`
on, so `getOrCreateLoginSessionForIdpInitiatedSso` falls back to the client's own
`saml_idp_initiated_sso_relay_state` for the outgoing value. Therefore:

- **Okta's "Default RelayState" (or any vendor-side relay value) is discarded.** Setting it
  to a client ID does nothing.
- **RelayState cannot select which client the user lands in.** Routing is entirely the
  `{urlName}` path segment — so one vendor-side tile serves exactly **one** client; a second
  client needs its own vendor-side app whose ACS/Reply URL carries that client's `{urlName}`.

## Binding selection — and why an OIDC target needs REST

`SamlService.getUrlAndBindingForIdpInitiatedSso`, strict priority:

1. `saml_assertion_consumer_url_post` → **POST**
2. else client `adminUrl` (*Master SAML Processing URL* — **not** "Home URL"/`baseUrl`) → **POST**
3. else `saml_assertion_consumer_url_redirect` → **REDIRECT** (GET)
4. else error (`INVALID_REDIRECT_URI`, "SAML assertion consumer url not set up")

And at response-build time `SamlProtocol.isPostBinding()` is
`POST.equals(clientNote(SAML_BINDING)) || samlClient.forcePostBinding()` — so
`forcePostBinding=true` silently overrides a REDIRECT choice from case 3.

An OIDC target therefore needs case 3 with cases 1–2 **unset** *and* `forcePostBinding=false`
— three settings, any one of which silently re-forces POST. `createSamlClient` cannot express
that, hence the REST fallback. A plain OIDC web app cannot consume an incoming SAML POST body,
but it can harmlessly ignore unknown query params on a GET.

**Be honest about what the OIDC recipe is.** Keycloak still builds and sends a real (and
ignored) SAML artifact to that URL. What makes it work is that the Keycloak SSO session cookie
is already set by the time the browser arrives, so the app's own ordinary OIDC redirect
completes silently. It's a session-bootstrap trick, not a native OIDC IdP-initiated flow.

Beware the naive success check: "a tile logs someone in" passes even when the delivery shape
is wrong, because Keycloak builds a SAML response for an OIDC client quite happily and the
cookie is set either way. Check **how** the browser was delivered.

## Steps (new SAML client — the case MCP does cover)

1. `whoAmI` — confirm caller and control-plane realm.
2. Confirm `deploymentId` + `deploymentRealm`, and the vendor IdP's `alias` via
   `listIdentityProviders`.
3. Agree a short, lowercase, whitespace-free `urlName` with the developer.
4. Call `createSamlClient` with `deploymentId`, `deploymentRealm`, the SP's `clientId`
   (entity ID) and `assertionConsumerServiceUrl` (or `spMetadataXml`), plus
   `idpInitiatedSsoUrlName` and `brokeredIdpAlias` = the vendor IdP alias. Echo the values
   back before calling.
5. Present the returned **`idpInitiatedSsoUrl`** prominently — that exact string goes into
   the vendor console (Okta **Single sign-on URL**, Entra **Reply URL**). Because
   `brokeredIdpAlias` was passed it will be the
   `/broker/{alias}/endpoint/clients/{urlName}` form. For Entra, leave **Sign on URL blank**;
   for Okta, leave **Default RelayState** blank (it is inert here).

## Steps (existing client, or an OIDC target — raw Admin REST)

Say out loud that no MCP tool covers this, then:

```bash
ID=$(curl -s "$BASE/admin/realms/$REALM/clients?clientId=$CLIENT_ID" -H "$H" | jq -r '.[0].id')
curl -s "$BASE/admin/realms/$REALM/clients/$ID" -H "$H" > /tmp/client.json

# SAML client target - the url name is all that's missing:
jq '.attributes["saml_idp_initiated_sso_url_name"]="my-reports-tile"' \
  /tmp/client.json > /tmp/c2.json

# OIDC client target - url name PLUS forcing the REDIRECT branch:
jq '.attributes["saml_idp_initiated_sso_url_name"]="my-portal-tile"
    | .attributes["saml_assertion_consumer_url_redirect"]="http://localhost:9999/"
    | .attributes["saml_assertion_consumer_url_post"]=""
    | .attributes["saml.force.post.binding"]="false"
    | .adminUrl=""' /tmp/client.json > /tmp/c2.json

curl -s -X PUT "$BASE/admin/realms/$REALM/clients/$ID" -H "$H" \
  -H 'Content-Type: application/json' --data-binary @/tmp/c2.json
```

Client update is a full-representation `PUT`: **read, merge, write back**. Never `PUT` a
hand-built partial — it blanks every field it omits. Then read the attribute back off the
client rather than trusting the write.

## Verify

`listClients` to confirm the clients are enabled and carry the expected attributes. Then fire
an unsolicited response at the endpoint (POST binding: `SAMLResponse` is base64 of the **raw**
XML, *not* deflated; no `InResponseTo`) and look at the delivery:

- OIDC target ⇒ a **302/303** whose `Location` is the app's main page.
- SAML target ⇒ a **200 HTML auto-POST form** whose action is the app's ACS.

Decoding the delivered `SAMLResponse` (redirect binding deflates before base64; POST binding
does not) shows a `<saml:Audience>` equal to the target client's `clientId` — the unambiguous
answer to "which client did the user land in".

## Common errors

- **HTTP 400 "Client not found."** — the `{urlName}` matches no client's
  `saml_idp_initiated_sso_url_name`, or that client is disabled.
- **HTTP 400 "Wrong client protocol."** — the *direct* endpoint was used against an OIDC
  client; only the **broker** endpoint skips that check. Ensure `brokeredIdpAlias` was passed
  (or build the broker URL by hand).
- **App gets a POST it can't handle** — POST binding won via case 1/2 or `forcePostBinding`.
  For an OIDC target this is the expected `createSamlClient` outcome; use REST instead.
- **Thrashing on `createSamlClient`/`deleteClient`** — if you're on the second or third
  create/delete cycle, stop: there is no argument combination that adds settings to an
  existing client or produces a REDIRECT binding. Switch to REST.
- **A second tile for a second client doesn't work** — expected; RelayState can't route. One
  vendor-side app per client.
