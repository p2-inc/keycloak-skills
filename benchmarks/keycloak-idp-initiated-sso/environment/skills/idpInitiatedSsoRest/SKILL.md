---
name: idpInitiatedSsoRest
description: >-
  Wire IdP-initiated SSO ("portal tiles") from an already-federated SAML identity provider
  such as Okta or Microsoft Entra ID into ONE specific Keycloak client, using the Admin
  REST API only (no MCP server involved). Use this whenever someone asks for an Okta
  dashboard tile or an Entra "My Apps" tile that drops the user straight inside a
  particular application already logged in, for an app-embed link, or for "IdP-initiated
  SSO" / "unsolicited SAML response" into a named client. Covers the broker endpoint
  /realms/{realm}/broker/{alias}/endpoint/clients/{urlName}, the three CLIENT attributes
  that control it, Keycloak's strict binding-selection priority and the extra steps an
  OIDC target needs, and why RelayState cannot choose the client. Not plain
  "let our users log in with Okta/Entra" federation - that is ordinary SP-initiated
  brokering, one login button serving every client.
---

# IdP-initiated SSO into one client (Okta / Entra tile) — via raw Admin REST

## What this is, and what it is NOT

Normally the **app** starts the login (SP-initiated): the user hits the app, the app
redirects to Keycloak, Keycloak may redirect on to a corporate IdP. **IdP-initiated** is the
reverse: the user is already in an external portal — an Okta dashboard tile, an Entra ID "My
Apps" tile — clicks it, and lands *inside one specific application*, already authenticated,
with that app never having issued a request.

This is narrow and advanced. A plain "let our users log in with Okta/Entra" request is
ordinary SP-initiated brokering (one login button serving every client) — not this. Use this
only when the ask is a portal tile / app-embed link targeting **one** downstream client.

## Two different endpoints — pick the right one first

Verified against Keycloak's source (`org.keycloak.protocol.saml.SamlService`,
`org.keycloak.broker.saml.SAMLEndpoint`):

| Who starts it | Endpoint | Client protocol allowed |
|---|---|---|
| **Keycloak itself** (a bookmark/portal link straight into Keycloak) | `{base}/realms/{realm}/protocol/saml/clients/{urlName}` | **SAML clients only** — `SamlService.idpInitiatedSSO` calls `isClientProtocolCorrect()` and rejects anything else with HTTP 400 "Wrong client protocol." |
| **An external SAML IdP** (Okta/Entra tile) POSTing an unsolicited SAML response through Keycloak | `{base}/realms/{realm}/broker/{alias}/endpoint/clients/{urlName}` | **any enabled client, including OIDC** — `SAMLEndpoint.samlIdpInitiatedSSO` resolves the target with `searchClientsByAttributes` and filters only on `ClientModel::isEnabled`; there is **no** protocol check |

That asymmetry is the single most useful fact here: **it is the reason an OIDC application
can be the target of a tile at all.** A tile always uses the **broker** path.

The vendor must already be brokered as a **SAML** identity provider; the `{alias}` in that
URL is that provider. If it isn't federated yet, do that first — this mechanism is
SAML-only, there is no OIDC-broker equivalent.

## The settings that matter — all on the CLIENT, not the identity provider

**A SAML identity provider has no IdP-initiated settings.** Verified by enumerating every
getter on `org.keycloak.broker.saml.SAMLIdentityProviderConfig`: there is no "IDP Initiated
SSO URL Name" and no "IDP Initiated SSO Relay State" there. Both are **client** attributes.
The provider's only contribution is its `alias` appearing in the URL above.

This is trap #1: the request arrives phrased entirely in terms of Okta and Entra, so the
identity-provider representation is where everyone looks first. Nothing goes there.

| Client attribute | Admin console label | Role |
|---|---|---|
| `saml_idp_initiated_sso_url_name` | IDP Initiated SSO URL Name | **Mandatory.** The `{urlName}` path segment. Keycloak resolves the target client by matching exactly this attribute. Empty ⇒ IdP-initiated login disabled for this client. |
| `saml_idp_initiated_sso_relay_state` | IDP Initiated SSO Relay State | Optional. The **outgoing** RelayState Keycloak hands the downstream SP (a deep-link hint). Not routing — see below. |
| `saml.force.post.binding` | Force POST Binding | Must be **`false`** for the OIDC-client recipe. |

### RelayState: what it does and does not do

On the broker path, `SAMLEndpoint.handleLoginResponse` takes the `{urlName}` branch and
**never reads the inbound `RelayState`** the vendor sent; `samlIdpInitiatedSSO` passes `null`
downstream, so `getOrCreateLoginSessionForIdpInitiatedSso` falls back to the *client's own*
`saml_idp_initiated_sso_relay_state` attribute for the outgoing value. So:

- **Okta's "Default RelayState", or any vendor-side relay value, is discarded** on this path.
  Setting it to a client ID does nothing.
- **RelayState cannot select which client the user lands in.** Routing is 100% the
  `{urlName}` path segment. One vendor-side tile therefore serves exactly **one** client; a
  second client needs its own vendor-side app whose ACS/Reply URL bakes in that client's own
  `{urlName}`.

This is trap #2: RelayState looks exactly like the routing mechanism, and Okta even gives you
a field for it.

## Binding selection — strict priority, and the OIDC-client recipe

`SamlService.getUrlAndBindingForIdpInitiatedSso` picks where and how to deliver, in order:

1. `saml_assertion_consumer_url_post` set → **POST** to that URL.
2. else client's **Admin URL** (`adminUrl`; labeled *Master SAML Processing URL* — **not**
   "Home URL"/`baseUrl`, a naming trap) → **POST**.
3. else `saml_assertion_consumer_url_redirect` set → **REDIRECT** (GET) to that URL.
4. else → error, `INVALID_REDIRECT_URI` / "SAML assertion consumer url not set up".

Then, when the response is built, `SamlProtocol.isPostBinding()` returns
`POST.equals(clientNote(SAML_BINDING)) || samlClient.forcePostBinding()` — so
**`forcePostBinding=true` silently overrides a REDIRECT choice from case 3.**

Trap #3: reaching case 3 means clearing **two** attributes that outrank it *and* a flag that
overrides it afterwards. Any one of the three left set sends an HTML auto-POST form.

### a. SAML client target

Set `saml_idp_initiated_sso_url_name`. POST binding via case 1 is correct and expected — a
SAML app can read the assertion.

### b. OIDC client target

A plain web app cannot consume an incoming SAML POST body, but it *can* harmlessly ignore
unknown query parameters on a GET. So force the REDIRECT branch:

- set `saml_assertion_consumer_url_redirect` = the app's **main page**,
- leave `saml_assertion_consumer_url_post` **unset/empty** and `adminUrl` **unset/empty**
  (either one wins and forces POST),
- set `saml.force.post.binding` = **`false`**,
- set `saml_idp_initiated_sso_url_name`.

**Be honest about what this is.** Keycloak still builds and sends a real (and ignored) SAML
artifact to that URL; the app gets nothing usable from the landing request itself. What makes
it work is that the **Keycloak SSO session cookie is already set** by the time the browser
arrives — so the app's own ordinary OIDC redirect, issued a moment later, completes silently
with no login prompt. It is a session-bootstrap trick, not a native OIDC IdP-initiated flow.
Say so rather than implying the tile hands the app tokens.

Trap #4: "a tile logs someone in" passes even when the shape is wrong, because Keycloak
builds a SAML response for an OIDC client quite happily and the cookie is set either way.
Check **how** the browser was delivered, not just that a session appeared.

## Steps

```bash
BASE=http://localhost:8080/auth      # include the relative path if configured
REALM=acme
H="Authorization: Bearer $ADMIN_TOKEN"
```

1. **Confirm the SAML IdP alias(es)** — the tile URL needs one, and nothing on the provider
   itself changes:
   ```bash
   curl -s "$BASE/admin/realms/$REALM/identity-provider/instances" -H "$H" \
     | jq '.[] | select(.providerId=="saml") | {alias, enabled}'
   ```
2. **Set the client attributes.** Keycloak's client update is a full-representation `PUT`, so
   **read, merge, write back** — never `PUT` a hand-built partial, it blanks every field it
   omits:
   ```bash
   ID=$(curl -s "$BASE/admin/realms/$REALM/clients?clientId=$CLIENT_ID" -H "$H" | jq -r '.[0].id')
   curl -s "$BASE/admin/realms/$REALM/clients/$ID" -H "$H" > /tmp/client.json

   # SAML client target:
   jq '.attributes["saml_idp_initiated_sso_url_name"]="my-reports-tile"' \
     /tmp/client.json > /tmp/c2.json

   # OIDC client target - also clears the two POST-forcing settings and the flag:
   jq '.attributes["saml_idp_initiated_sso_url_name"]="my-portal-tile"
       | .attributes["saml_assertion_consumer_url_redirect"]="http://localhost:9999/"
       | .attributes["saml_assertion_consumer_url_post"]=""
       | .attributes["saml.force.post.binding"]="false"
       | .adminUrl=""' /tmp/client.json > /tmp/c2.json

   curl -s -X PUT "$BASE/admin/realms/$REALM/clients/$ID" -H "$H" \
     -H 'Content-Type: application/json' --data-binary @/tmp/c2.json
   ```
3. **Read the attribute back** off the client — don't trust the write.
4. **Compute the URL to hand each vendor**, one per client per provider:
   ```
   {BASE}/realms/{REALM}/broker/{ALIAS}/endpoint/clients/{urlName}
   ```
   That string goes into Okta's **Single sign-on URL** or Entra's **Reply URL**. For Entra,
   leave **Sign on URL blank** — a populated Sign on URL makes the tile do SP-initiated
   login instead. For Okta, leave **Default RelayState** blank; it is inert here.

## Verify

Fire an unsolicited response at the endpoint (POST binding: `SAMLResponse` is base64 of the
**raw** XML, *not* deflated; no `InResponseTo`, which is what makes it unsolicited) and look
at how the browser is delivered:

- OIDC target ⇒ a **302/303** whose `Location` is the app's main page.
- SAML target ⇒ a **200 HTML auto-POST form** whose action is the app's ACS.

Decoding the delivered `SAMLResponse` (redirect binding deflates before base64; POST binding
does not) shows a `<saml:Audience>` equal to the target client's `clientId` — that is the
unambiguous answer to "which client did the user land in".

## Common errors

- **HTTP 400 "Client not found."** — the `{urlName}` matches no client's
  `saml_idp_initiated_sso_url_name` (or that client is disabled). Re-read the attribute back.
- **HTTP 400 "Wrong client protocol."** — the *direct* `/protocol/saml/clients/...` endpoint
  was used against an OIDC client. Use the **broker** endpoint; only it skips the check.
- **"SAML assertion consumer url not set up" / `INVALID_REDIRECT_URI`** — none of the three
  binding sources is set. For an OIDC target, `saml_assertion_consumer_url_redirect` is the
  one you want.
- **App receives a POST it can't handle, or an auto-POST page appears** —
  `saml.force.post.binding` is still true, or `saml_assertion_consumer_url_post`/`adminUrl`
  is still set and outranks the redirect URL.
- **Developer set "Home URL" (`baseUrl`) expecting it to matter** — that field isn't read by
  this code path at all. The POST-forcing fallback is `adminUrl`.
- **A second tile for a second client doesn't work** — expected; RelayState can't route. Each
  client needs its own vendor-side app with its own `{urlName}`.
