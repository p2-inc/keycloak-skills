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

Use the **broker** endpoint. That is decided by *who initiates* — an Okta/Entra tile POSTs an
unsolicited SAML response, which only the broker endpoint accepts — not by the target client's
protocol.

> **Do not read the "including OIDC" cell as "so make the tile target an OIDC client."** It is a
> true fact about the endpoint and a useful one for debugging, but it is **not** how the OIDC case
> is built here — see the next section. The tile target is a SAML client either way.

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

### The tile target is a SAML client in BOTH cases

**`"protocol": "saml"` either way.** "The app speaks OIDC" describes the *application*, not the
Keycloak client you create for the tile. What differs between the two cases is two attributes:

| | App speaks SAML | App speaks OIDC (SPA) |
|---|---|---|
| `protocol` | `saml` | `saml` — *same* |
| `saml_idp_initiated_sso_url_name` | `myapp` | `myapp` — *same* |
| `saml.force.post.binding` | `true` (default) | **`false`** |
| ACS attribute carrying the app's URL | `saml_assertion_consumer_url_post` | **`saml_assertion_consumer_url_redirect`** |
| `adminUrl` | unset | unset (it would force POST) |

### a. The app speaks SAML

Configure the SP side as normal (ACS URL, entity ID, signing cert). Set
`saml_idp_initiated_sso_url_name`. POST binding via step 1 is correct and expected.

### b. The app speaks OIDC (a SPA)

**Create a second, dedicated SAML client as the tile target. Do not put these attributes on the
app's own OIDC client.** The SPA keeps its OIDC client, its `redirectUris`, its everything —
untouched. The SAML client sits beside it purely to catch the tile click and set the SSO cookie.

A plain web app cannot consume an incoming SAML POST body, but it *can* harmlessly ignore unknown
query parameters on a GET. So on that **SAML shim client**, force the REDIRECT branch:

- set `saml_assertion_consumer_url_redirect` = the SPA's **home URL** (its main page),
- leave `saml_assertion_consumer_url_post` **unset** and `adminUrl` **unset** (either one wins and
  forces POST),
- set `saml.force.post.binding` = **`false`**,
- set `saml_idp_initiated_sso_url_name`.

> **Why not just add these attributes to the OIDC client?** It is not hard-broken — Keycloak forces
> the auth session's protocol to `saml` (`SamlService.getOrCreateLoginSessionForIdpInitiatedSso`
> calls `authSession.setProtocol(SamlProtocol.LOGIN_PROTOCOL)`), and the finish path resolves the
> protocol from the *auth session*, not the client (`AuthenticationManager` line ~951) — so a SAML
> response does get built. But it is the wrong shape and carries real cost: it mutates the app's
> **live** client, leaves SAML attributes on a client whose `protocol` contradicts them, produces an
> unsigned assertion (an OIDC client has no SAML signing keys), and makes "delete and re-create to
> fix the tile" a destructive act against the real app. A separate shim is free to delete.

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
2. **Create the tile-target client — `protocol: saml` in both cases.** Creating fresh is the normal
   path: a new client has no `adminUrl` and no POST ACS unless you set one, so binding-priority
   cases 1–2 are empty by construction and the REDIRECT branch is reachable.

   **a. The app speaks SAML** — the app's real SAML client *is* the tile target:
   ```bash
   curl -s -X POST "$BASE/admin/realms/$REALM/clients" -H "$H" \
     -H 'Content-Type: application/json' -d '{
       "clientId": "my-app",
       "protocol": "saml",
       "enabled": true,
       "attributes": {
         "saml_idp_initiated_sso_url_name": "myapp",
         "saml_assertion_consumer_url_post": "https://app.example.com/saml/acs",
         "saml.force.post.binding": "true",
         "saml.authnstatement": "true",
         "saml_name_id_format": "username"
       }
     }'
   ```

   **b. The app speaks OIDC (a SPA)** — a **separate SAML shim** beside the SPA's own OIDC client,
   which is not touched. Note `protocol: saml`, the *redirect* ACS, and no `adminUrl`:
   ```bash
   curl -s -X POST "$BASE/admin/realms/$REALM/clients" -H "$H" \
     -H 'Content-Type: application/json' -d '{
       "clientId": "my-app-tile",
       "name": "Tile shim for my-app (SPA)",
       "protocol": "saml",
       "enabled": true,
       "attributes": {
         "saml_idp_initiated_sso_url_name": "myapp",
         "saml_assertion_consumer_url_redirect": "https://app.example.com/",
         "saml.force.post.binding": "false",
         "saml.authnstatement": "true",
         "saml_name_id_format": "username"
       }
     }'
   ```
   Give the shim its **own** `clientId`, distinct from the SPA's — they coexist in the same realm.

3. **Only if the target client already exists**, read-merge-`PUT` instead of creating.

   > ⚠️ **Two opposite rules in the same `PUT`, and this catches people.** Top-level fields
   > (`redirectUris`, `rootUrl`, …) are **replaced** — omit one and it is blanked, which is why you
   > read the full representation first. But `attributes` are **merged**: `RepresentationToModel`
   > iterates only the keys *present* in the payload and calls `setAttribute` on each, with no
   > removal pass. So **you cannot delete an attribute by leaving it out** — it survives. To remove
   > one, send the key explicitly with a JSON `null` (verified against a live Keycloak: `null`
   > removes it; `""` leaves an empty-string attribute behind, which still counts as "set" for
   > binding-priority case 1).
   ```bash
   ID=$(curl -s "$BASE/admin/realms/$REALM/clients?clientId=$CLIENT_ID" -H "$H" | jq -r '.[0].id')
   curl -s "$BASE/admin/realms/$REALM/clients/$ID" -H "$H" > /tmp/client.json

   jq '.attributes["saml_idp_initiated_sso_url_name"]="myapp"' /tmp/client.json > /tmp/c2.json

   curl -s -X PUT "$BASE/admin/realms/$REALM/clients/$ID" -H "$H" \
     -H 'Content-Type: application/json' --data-binary @/tmp/c2.json
   ```
   This applies to an existing **SAML** client. For a SPA, don't retrofit its OIDC client — create
   the shim in step 2b instead.

4. **Read the attributes back and confirm the shape** — every failure on the OIDC path is a silent
   fallback to POST, so don't skip this:
   ```bash
   curl -s "$BASE/admin/realms/$REALM/clients?clientId=my-app-tile" -H "$H" \
     | jq '.[0] | {protocol, adminUrl, attributes: (.attributes | {
         saml_idp_initiated_sso_url_name,
         saml_assertion_consumer_url_redirect,
         saml_assertion_consumer_url_post,
         "saml.force.post.binding"})}'
   ```
   Expect `protocol: "saml"`, the redirect URL set, POST ACS and `adminUrl` absent/empty, and
   `saml.force.post.binding: "false"`.

5. **Compute the URL to hand the vendor**:
   ```
   {BASE}/realms/{REALM}/broker/{IDP_ALIAS}/endpoint/clients/{urlName}
   ```
6. **Do the vendor-side configuration** — read exactly one:
   `references/idp/okta-idp-initiated.md` or `references/idp/entra-idp-initiated.md`.
   The vendor side is **identical** for cases a and b, and identical between Okta and Entra ID: the
   vendor always POSTs an unsolicited SAML response to that same broker URL. POST-vs-REDIRECT
   concerns only the second hop (Keycloak → the app) and is invisible to the IdP.

## Verify

Click the tile in the vendor's portal. The user should land in the target app already
authenticated, with no visit to the app first. Then check the realm's login events
(`/admin/realms/{realm}/events?type=LOGIN`) show a login for the intended client.

## Common errors

- **"Client not found" / HTTP 400 at Keycloak** — the `{urlName}` in the vendor's ACS URL doesn't
  match any client's `saml_idp_initiated_sso_url_name` (or that client is disabled). Re-read the
  attribute back from the client; don't trust the console form having been saved.
- **"Wrong client protocol."** — the *direct* endpoint (`/protocol/saml/clients/...`) was used
  against a non-SAML client. Use the **broker** endpoint; only it skips the protocol check. If the
  tile target was built per step 2 it is a SAML client anyway, so this points at the wrong endpoint
  rather than the wrong client.
- **"SAML assertion consumer url not set up" / `INVALID_REDIRECT_URI`** — none of the three
  binding sources in the priority list is set. For a SPA target, `saml_assertion_consumer_url_redirect`
  is the one you want.
- **SPA receives a POST it can't handle, or a form-autopost page appears** — `forcePostBinding` is
  still `true`, or `saml_assertion_consumer_url_post`/`adminUrl` is still set and outranks the
  redirect URL. Re-run step 4 and compare against the expected shape.
- **SAML attributes ended up on the app's own OIDC client** — the shim wasn't created; the tile
  target must be its own `protocol: saml` client (step 2b). To undo, read the OIDC client and `PUT`
  it back with each stray key set to **`null`** — deleting them from the JSON does nothing, per the
  merge rule in step 3:
  ```bash
  jq '.attributes["saml_idp_initiated_sso_url_name"]=null
      | .attributes["saml_assertion_consumer_url_redirect"]=null
      | .attributes["saml_assertion_consumer_url_post"]=null
      | .attributes["saml.force.post.binding"]=null' /tmp/client.json > /tmp/c2.json
  ```
- **Developer set "Home URL" (`baseUrl`) expecting it to matter** — it isn't read by this code path
  at all. The POST-forcing fallback is `adminUrl`.
- **A second tile for a second client doesn't work** — expected; RelayState can't route. Each
  client needs its own vendor-side app with its own `{urlName}`.
