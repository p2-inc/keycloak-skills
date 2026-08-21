# IdP-initiated SSO into one client (Okta / Entra ID tile) — via raw Admin REST

## What is being asked for

Normally the **app** starts the login (SP-initiated): a user hits the app, the app redirects to
Keycloak, Keycloak maybe redirects on to a corporate IdP. **IdP-initiated** is the reverse: the
user is already in an external portal — an Okta dashboard tile, an Entra ID "My Apps" tile — clicks
it, and lands *inside one specific application*, already authenticated, with that app never having
issued a request.

This is a **narrow, advanced** capability. Do not route a plain "let our users log in with
Okta/Entra ID" request here — that's `admin:idp-federation` (ordinary SP-initiated brokering, one
login button serving every client). Only use this intent when the developer specifically wants a
portal tile / app-embed link that targets **one** downstream client.

## Two different endpoints — pick the right one first

Verified against Keycloak's source (`org.keycloak.protocol.saml.SamlService` and
`org.keycloak.broker.saml.SAMLEndpoint`):

| Who starts it | Endpoint | Client protocol allowed |
|---|---|---|
| **Keycloak itself** (no external IdP; a bookmark or portal link straight into Keycloak) | `{BASE}/realms/{REALM}/protocol/saml/clients/{urlName}` | **SAML clients only** — `SamlService.idpInitiatedSSO` calls `isClientProtocolCorrect()` and rejects anything else with "Wrong client protocol." |
| **An external SAML IdP** (Okta/Entra tile) POSTing an unsolicited SAML response through Keycloak | `{BASE}/realms/{REALM}/broker/{IDP_ALIAS}/endpoint/clients/{urlName}` | **any enabled client, including OIDC** — `SAMLEndpoint.samlIdpInitiatedSSO` filters only on `ClientModel::isEnabled`; it does **not** perform the protocol check the direct path does |

That asymmetry is the single most useful fact in this document: **it is the reason an
OIDC application can be the target of an Okta/Entra tile at all.** The broker path is the one
these vendor walkthroughs use.

## Prerequisite: the vendor must already be brokered as a SAML IdP

The `{IDP_ALIAS}` in that URL is an existing SAML identity provider in the realm. If Okta/Entra
isn't federated yet, do `admin:idp-federation` first (SAML path — this mechanism is SAML-only;
RelayState-chained IdP-initiated SSO has no OIDC-broker equivalent) and note the alias.

## The three settings that matter — all on the CLIENT, not the IdP

**A SAML identity provider has no IdP-initiated settings.** Verified by enumerating every getter on
`org.keycloak.broker.saml.SAMLIdentityProviderConfig`: there is no "IDP Initiated SSO URL Name" and
no "IDP Initiated SSO Relay State" there. Both are **client** attributes. The IdP's only
contribution is its `alias` appearing in the URL above.

| Client attribute | Admin console label (SAML clients) | Role |
|---|---|---|
| `saml_idp_initiated_sso_url_name` | IDP Initiated SSO URL Name | **Mandatory.** The `{urlName}` segment. Keycloak resolves the target client by `searchClientsByAttributes` on exactly this attribute. Empty ⇒ IdP-initiated login disabled for this client. |
| `saml_idp_initiated_sso_relay_state` | IDP Initiated SSO Relay State | Optional. The **outgoing** RelayState Keycloak hands the downstream SP (a deep-link hint). Not a routing mechanism — see below. |
| `saml.force.post.binding` | Force POST Binding | Must be **`false`** for the OIDC-client recipe. See binding selection below. |

### RelayState: what it does and does not do

On the broker path, `SAMLEndpoint.handleLoginResponse` takes the `{urlName}` branch and **never
reads the inbound `RelayState`** the vendor sent; `samlIdpInitiatedSSO` then passes `null`
downstream, so `getOrCreateLoginSessionForIdpInitiatedSso` falls back to the *client's own*
`saml_idp_initiated_sso_relay_state` attribute for the outgoing value.

Consequences to state plainly to the developer:

- **Okta's "Default RelayState" / any vendor-side relay value is discarded** on this path. It is
  not the vendor-side equivalent of the client attribute, and setting it to a client ID does
  nothing.
- **RelayState cannot select which client the user lands in.** Routing is 100% the `{urlName}` in
  the URL path. So **one vendor-side app/tile targets exactly one client**; a second client needs
  its own vendor-side app (or duplicate) whose ACS/Reply URL bakes in that client's own `{urlName}`.

## Binding selection — strict priority, and the OIDC-client recipe

`SamlService.getUrlAndBindingForIdpInitiatedSso` picks where and how to deliver, in this order:

1. `saml_assertion_consumer_url_post` set → **POST** binding to that URL.
2. else client's **Admin URL** (`adminUrl`; labeled *Master SAML Processing URL* — **not** "Home
   URL"/`baseUrl`, a naming trap) → **POST** binding.
3. else `saml_assertion_consumer_url_redirect` set → **REDIRECT** (GET) binding to that URL.
4. else → error, `INVALID_REDIRECT_URI` / "SAML assertion consumer url not set up".

Then, when the response is actually built, `SamlProtocol.isPostBinding()` returns
`POST.equals(clientNote(SAML_BINDING)) || samlClient.forcePostBinding()` — so **`forcePostBinding=true`
silently overrides a REDIRECT choice from step 3.** That is why the OIDC recipe needs it `false`.

### a. SAML client target

Configure the SP side as normal (ACS URL, entity ID, signing cert). Set
`saml_idp_initiated_sso_url_name`. POST binding via step 1 is correct and expected.

### b. OIDC client target

A plain web app cannot consume an incoming SAML POST body, but it *can* harmlessly ignore unknown
query parameters on a GET. So force the REDIRECT branch:

- set `saml_assertion_consumer_url_redirect` = the app's **home URL** (its main page),
- leave `saml_assertion_consumer_url_post` **unset** and `adminUrl` **unset** (either one wins and
  forces POST),
- set `saml.force.post.binding` = **`false`**,
- set `saml_idp_initiated_sso_url_name`.

**Be honest with the developer about what this is.** Keycloak still builds and sends a real (and
ignored) SAML artifact to that URL. The app gets nothing usable from the landing request itself.
What actually makes this work is that the **Keycloak SSO session cookie is already set** by the
time the browser arrives — so the app's own ordinary OIDC redirect, issued a moment later,
completes silently with no login prompt. This is a session-bootstrap trick, not a native OIDC
IdP-initiated flow. Say so rather than implying the tile hands the app tokens.

## Steps

```bash
BASE=http://localhost:8080      # include the relative path if configured
REALM=myrealm
H="Authorization: Bearer $ADMIN_TOKEN"
```

1. **Confirm the SAML IdP alias** exists:
   ```bash
   curl -s "$BASE/admin/realms/$REALM/identity-provider/instances" -H "$H" \
     | jq '.[] | select(.providerId=="saml") | {alias, enabled}'
   ```
2. **Set the client attributes.** Keycloak's client update is a full-representation `PUT`, so read,
   merge, write back — never `PUT` a hand-built partial representation, it will blank fields:
   ```bash
   ID=$(curl -s "$BASE/admin/realms/$REALM/clients?clientId=$CLIENT_ID" -H "$H" | jq -r '.[0].id')
   curl -s "$BASE/admin/realms/$REALM/clients/$ID" -H "$H" > /tmp/client.json

   # SAML client target:
   jq '.attributes["saml_idp_initiated_sso_url_name"]="my-client"' /tmp/client.json > /tmp/c2.json

   # OIDC client target (note: also clears the two POST-forcing settings):
   jq '.attributes["saml_idp_initiated_sso_url_name"]="my-client"
       | .attributes["saml_assertion_consumer_url_redirect"]="https://app.example.com/"
       | .attributes["saml_assertion_consumer_url_post"]=""
       | .attributes["saml.force.post.binding"]="false"
       | .adminUrl=""' /tmp/client.json > /tmp/c2.json

   curl -s -X PUT "$BASE/admin/realms/$REALM/clients/$ID" -H "$H" \
     -H 'Content-Type: application/json' --data-binary @/tmp/c2.json
   ```
3. **Compute the URL to hand the vendor**:
   ```
   {BASE}/realms/{REALM}/broker/{IDP_ALIAS}/endpoint/clients/{urlName}
   ```
4. **Do the vendor-side configuration** — read exactly one:
   `references/idp/okta-idp-initiated.md` or `references/idp/entra-idp-initiated.md`.

## Verify

Click the tile in the vendor's portal. The user should land in the target app already
authenticated, with no visit to the app first. Then check the realm's login events
(`/admin/realms/{realm}/events?type=LOGIN`) show a login for the intended client.

## Common errors

- **"Client not found" / HTTP 400 at Keycloak** — the `{urlName}` in the vendor's ACS URL doesn't
  match any client's `saml_idp_initiated_sso_url_name` (or that client is disabled). Re-read the
  attribute back from the client; don't trust the console form having been saved.
- **"Wrong client protocol."** — the *direct* endpoint (`/protocol/saml/clients/...`) was used
  against an OIDC client. Use the **broker** endpoint instead; only it skips the protocol check.
- **"SAML assertion consumer url not set up" / `INVALID_REDIRECT_URI`** — none of the three
  binding sources in the priority list is set. For an OIDC target, `saml_assertion_consumer_url_redirect`
  is the one you want.
- **App receives a POST it can't handle, or a form-autopost page appears** — `forcePostBinding` is
  still `true`, or `saml_assertion_consumer_url_post`/`adminUrl` is still set and outranks the
  redirect URL.
- **Developer set "Home URL" (`baseUrl`) expecting it to matter** — it isn't read by this code path
  at all. The POST-forcing fallback is `adminUrl`.
- **A second tile for a second client doesn't work** — expected; RelayState can't route. Each
  client needs its own vendor-side app with its own `{urlName}`.
