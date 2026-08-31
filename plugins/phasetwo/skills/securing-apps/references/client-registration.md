<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# Registering the app's OIDC client — self-managed Keycloak (Admin REST)

## What this is

Every integration in this skill needs a Keycloak **client** to exist before the app can log anyone
in. This file covers both branches of Step 4: creating one, and widening one that already exists.

A *client* is the app authenticating **against** Keycloak. That is the opposite direction from an
*identity provider*, which federates an external login **into** Keycloak — if the request is "log in
with Okta/Google", it belongs to the `keycloak` skill, not here.

**This file is for `tooling=rest` only** — a Keycloak you run yourself (bare metal, Docker,
Kubernetes) where you hold admin credentials. A Phase Two hosted deployment has **no self-service
admin REST credential of any kind**: there is nothing to put in `$ADMIN_TOKEN`, so this file dead-ends
at Step 0. Use `client-registration-mcp.md` there instead. `rest` is not a fallback for `mcp`.

Also not this file: Keycloak's **Dynamic Client Registration** service
(`/realms/{realm}/clients-registrations/...`, driven by an initial access token). That is a separate
feature for apps that self-register. Everything below is the ordinary Admin REST API, which is what
you want when a human or an agent is registering one known app.

## Endpoints this file drives

| Purpose | Call |
|---|---|
| Mint an admin token | `POST /realms/master/protocol/openid-connect/token` |
| **Find out whether the client already exists**, and get its UUID | `GET /admin/realms/{realm}/clients?clientId={clientId}` |
| Read one client's full representation | `GET /admin/realms/{realm}/clients/{uuid}` |
| Create it (new branch) | `POST /admin/realms/{realm}/clients` |
| Update it (existing branch) — **whole representation** | `PUT /admin/realms/{realm}/clients/{uuid}` |
| Read a confidential client's secret | `GET /admin/realms/{realm}/clients/{uuid}/client-secret` |
| Rotate that secret | `POST /admin/realms/{realm}/clients/{uuid}/client-secret` |
| Read the previous secret during a grace period | `GET /admin/realms/{realm}/clients/{uuid}/client-secret/rotated` |

`{uuid}` is **not** the `clientId`. See Step 2 — this is the single most common 404 here.

## Step 0: environment and `$ADMIN_TOKEN`

```bash
BASE=http://localhost:8080        # include the relative path (e.g. /auth) if one is configured
REALM=myrealm                       # the realm the app logs in against — NOT master

# Mint $ADMIN_TOKEN from the built-in admin-cli client in `master` (skip if you already have one).
ADMIN_TOKEN=$(curl -s -X POST "$BASE/realms/master/protocol/openid-connect/token" \
  -d client_id=admin-cli -d grant_type=password \
  -d username=<admin-user> -d password=<admin-password> \
  | jq -r .access_token)
H="Authorization: Bearer $ADMIN_TOKEN"
```

- **`$REALM` is the app's realm, not `master`.** You authenticate *as* a `master` admin and act *on*
  the app's realm. Creating the client in `master` by mistake produces a client that exists, looks
  right in the console, and that the app can never log in against.
- **The token is short-lived** — minutes, not hours. A run that starts working and then returns `401`
  on every call has simply expired; re-run the block above rather than debugging permissions.

## Step 1: Decide the client type — from the app, not from preference

This is decided by Step 2's framework detection, and it is not a judgement call:

| App shape | Representation fields | Why |
|---|---|---|
| Browser SPA — React, Angular, Vue, vanilla | `"publicClient": true`, `"standardFlowEnabled": true`, plus the PKCE attribute | A browser bundle cannot keep a secret. Anyone can read it in devtools. Auth-code + **PKCE** instead. |
| Native mobile / desktop — Android, iOS, React Native | same, with a custom-scheme redirect URI | Same reason: the binary ships to the user's device. PKCE. |
| Server-side web app that renders pages — Next.js with Auth.js, Express with sessions | `"publicClient": false`, `"standardFlowEnabled": true` | The secret lives on a server the user never sees. |
| Backend service calling APIs with no user present | `"publicClient": false`, `"serviceAccountsEnabled": true`, `"standardFlowEnabled": false` | Client-credentials grant. No login UI, no redirect URIs. |

**A resource server (`app:protect-api`) usually needs no client of its own.** It validates tokens
issued to *other* clients. Create one only if the API also calls other services on its own behalf
(then: the service-account row). Don't create a client just because the intent mentioned Keycloak.

`bearerOnly` is still a field on `ClientRepresentation`, but it is a legacy access type — the current
admin console no longer offers it, and it buys a token validator nothing. Don't reach for it; prefer
"no client at all" for a pure resource server.

## Step 2: Find out which branch you are on — and get the UUID

**Do this before asking the developer anything.**

```bash
curl -s "$BASE/admin/realms/$REALM/clients?clientId=my-web-app" -H "$H" \
  | jq '.[] | {id, clientId, publicClient, protocol, enabled, redirectUris, webOrigins}'
```

This returns a **JSON array** — empty (`[]`) if nothing matches, one element if it does. The
`clientId` query parameter is an exact match on the human-readable id.

**`clientId` is not the UUID.** `clientId` is the string the app puts in its config
(`my-web-app`). The `id` field is a server-generated UUID, and it is what goes in every
`/clients/{uuid}` path below. Capture it once:

```bash
ID=$(curl -s "$BASE/admin/realms/$REALM/clients?clientId=my-web-app" -H "$H" | jq -r '.[0].id')
if [ -z "$ID" ] || [ "$ID" = "null" ]; then
  echo "no such client — you are on Branch A (create it)" >&2
fi
```

Guard that emptiness check. On an empty array `jq -r '.[0].id'` prints the literal string `null`, and
`PUT /clients/null` returns a `404` that reads like a permissions problem and is not one.

Cross-check against the app's own config (`.env`, `keycloak.json`, `application.properties`,
`app.config.js`): a `clientId` already sitting there means the client exists and its value is the
answer. Only ask outright when this is genuinely ambiguous.

## Step 3a: New client — `POST /clients`

**Never invent `clientId` or `redirectUris`.** They are the developer's; ask for each and wait for
the answer. Ask for the local-development URI at the same time as the production one — coming back to
add it later is the single most common reason to need Branch B an hour later.

### Public client (SPA, mobile) — PKCE, no secret

```bash
curl -s -X POST "$BASE/admin/realms/$REALM/clients" \
  -H "$H" -H 'Content-Type: application/json' -d '{
    "clientId": "my-web-app",
    "name": "My Web App",
    "protocol": "openid-connect",
    "enabled": true,
    "publicClient": true,
    "standardFlowEnabled": true,
    "implicitFlowEnabled": false,
    "directAccessGrantsEnabled": false,
    "serviceAccountsEnabled": false,
    "redirectUris": [
      "https://app.example.com/callback",
      "http://localhost:3000/callback"
    ],
    "webOrigins": [
      "https://app.example.com",
      "http://localhost:3000"
    ],
    "attributes": {
      "pkce.code.challenge.method": "S256",
      "post.logout.redirect.uris": "+"
    }
  }'
```

- **`"pkce.code.challenge.method": "S256"` is the whole point of a public client** and it is not on by
  default. Left unset, Keycloak *accepts* PKCE from a client that offers it but does not *require* it,
  so an authorization code intercepted from the redirect is replayable. Set it explicitly.
- `"implicitFlowEnabled": false` and `"directAccessGrantsEnabled": false` are deliberate. Implicit
  flow is deprecated; direct access grants (password grant) hands the user's password to the app,
  which is the thing OIDC exists to avoid. Turn them on only if something concrete needs them.
- `"post.logout.redirect.uris": "+"` means "the registered redirect URIs" and is what makes
  `post_logout_redirect_uri` work on logout. Without it, logout succeeds but the browser is left on
  Keycloak's own page instead of returning to the app.

For a **native mobile** client the redirect URI is a custom scheme or an app-claimed HTTPS link
(`com.example.myapp:/oauth2redirect`), and `webOrigins` is irrelevant — the token request comes from
the app process, not a browser, so no CORS preflight ever happens.

### Confidential client (server-side web app)

Same body with `"publicClient": false`, no PKCE attribute required, and:

```json
  "clientAuthenticatorType": "client-secret",
  "webOrigins": []
```

`webOrigins` is empty because the token exchange happens server-to-server. A server-rendered app that
*also* has browser JavaScript calling the token endpoint needs the origin listed; a pure BFF does not.

### Service-account client (no user present)

```json
  "publicClient": false,
  "standardFlowEnabled": false,
  "implicitFlowEnabled": false,
  "directAccessGrantsEnabled": false,
  "serviceAccountsEnabled": true
```

No `redirectUris`, no `webOrigins` — there is no browser and no user to redirect.

### Get the UUID and, for confidential clients, the secret

`POST /clients` returns **`201 Created` with an empty body**; the new UUID is only in the `Location`
header. The portable way to pick it up is to query for it (Step 2), which also confirms the create
landed:

```bash
ID=$(curl -s "$BASE/admin/realms/$REALM/clients?clientId=my-web-app" -H "$H" | jq -r '.[0].id')

# Confidential and service-account clients only:
curl -s "$BASE/admin/realms/$REALM/clients/$ID/client-secret" -H "$H" | jq -r .value
```

That endpoint returns `{"type":"secret","value":"..."}`. Show the value once, prominently, and tell
the developer to store it server-side.

**For a `public` client there is no secret** — say so explicitly rather than leaving the developer
hunting for one. The app uses PKCE. Calling `/client-secret` on a public client is not a useful
diagnostic; it does not mean the client is broken.

The app also needs the issuer and discovery URL, which are deterministic — no call required:

```
issuer        = {BASE}/realms/{REALM}
wellKnownUrl  = {BASE}/realms/{REALM}/.well-known/openid-configuration
```

Point the OIDC library at the well-known URL and it discovers every endpoint itself.

## Step 3b: Existing client — read, merge, `PUT`. Never a partial `PUT`.

The common case: the client works in production and now needs `http://localhost:3000/callback` for
local development.

> ⚠️ **`PUT /admin/realms/{realm}/clients/{uuid}` takes the WHOLE client representation.** Top-level
> fields you omit are **blanked**, silently, with a `204 No Content` that looks like success. Send
> only `{"redirectUris": [...]}` and you have just wiped the client's name, its protocol mappers, its
> flow bindings, its scopes, and its production web origins. There is no partial-update endpoint and
> no PATCH. **Always: `GET` the full representation, edit the fields you want, `PUT` it back.**

```bash
ID=$(curl -s "$BASE/admin/realms/$REALM/clients?clientId=my-web-app" -H "$H" | jq -r '.[0].id')

# 1. READ the current representation whole
curl -s "$BASE/admin/realms/$REALM/clients/$ID" -H "$H" > /tmp/client.json

# 2. MERGE — append to the existing lists, don't replace them
jq '.redirectUris = (.redirectUris + ["http://localhost:3000/callback"] | unique)
  | .webOrigins   = (.webOrigins   + ["http://localhost:3000"]         | unique)' \
  /tmp/client.json > /tmp/client-new.json

# 3. LOOK at what you are about to send. Anything you did not intend is a bug.
diff <(jq -S . /tmp/client.json) <(jq -S . /tmp/client-new.json)

# 4. PUT the whole thing back — expect 204 No Content
curl -s -o /dev/null -w '%{http_code}\n' \
  -X PUT "$BASE/admin/realms/$REALM/clients/$ID" -H "$H" \
  -H 'Content-Type: application/json' --data-binary @/tmp/client-new.json
```

Four things about this that are load-bearing:

- **Merge, don't overwrite.** `.redirectUris = ["http://localhost:3000/callback"]` drops production.
  The `+ [...] | unique` form above appends. Read the current values before deciding.
- **`attributes` behave the opposite way from every other field, and this catches people.** Top-level
  fields are replaced; `attributes` are **merged** — Keycloak iterates only the keys *present* in the
  payload and sets each, with no removal pass. So you **cannot delete an attribute by leaving it
  out**; it survives. To remove one, send the key explicitly with a JSON `null` (verified against a
  live Keycloak in this repo: `null` removes it, `""` leaves an empty-string attribute behind, which
  still counts as "set").
- **Don't reason about which omissions are safe.** Some fields do more than store a value —
  `serviceAccountsEnabled`, `protocolMappers` and `authorizationSettings` drive create/delete side
  effects on the objects behind them. Read-merge-`PUT` makes the question moot; a hand-built body
  reopens it every time.
- **`/tmp/client.json` may contain the client secret.** `GET /clients/{uuid}` returns the `secret`
  field for a confidential client, so these temp files are credential material: delete them
  afterwards, and keep them out of logs, shell history and version control.

**Never `DELETE` a live client to change an attribute.** It takes the client's secret, its role
mappings, its consent grants, and every session with it. Users are logged out and the app's
configured secret stops working.

## Step 4: Redirect URIs and web origins are different things

The single most common "it worked in testing and breaks in the browser" failure, and it is worth
stating to the developer explicitly rather than just setting both:

| | Authorizes | Fails when wrong |
|---|---|---|
| **`redirectUris`** | where Keycloak may send the user **back** after login | immediately and loudly — `Invalid redirect_uri` on the Keycloak error page, before login |
| **`webOrigins`** | the **CORS** origin the browser's token call may come from | late and quietly — login appears to succeed, then the token request fails CORS in the browser console |

A scripted or server-side test passes with a wrong `webOrigins` because nothing triggers CORS. Only a
real browser catches it. Set both.

Matching is **exact** — scheme, host, port, and path all count. `http://localhost:3000` and
`http://127.0.0.1:3000` are different origins. So are `https://app.example.com` and
`https://app.example.com/`.

`"webOrigins": ["+"]` means "exactly the origins of the registered redirect URIs" and is a reasonable
default for a browser app whose redirect URIs are already correct. `"*"` allows every origin — don't.

One extra trap that only exists on the REST path: if the client has a **`rootUrl`** set, a relative
`redirectUris` entry (`/callback`) resolves against it, and a `${authBaseUrl}`/`${authAdminUrl}`
placeholder is expanded by the server. A representation that looks wrong may be correct after
expansion — compare what the client *resolves to*, not the raw string, before editing it.

## Rotating a secret

```bash
curl -s -X POST "$BASE/admin/realms/$REALM/clients/$ID/client-secret" -H "$H" | jq -r .value
```

`POST` (not `GET`) to the same path regenerates the secret and returns the new one.

- **The old secret stops working immediately** unless a rotation grace period is configured, and
  every consumer still holding it fails to authenticate at once. Confirm with the developer that all
  consumers can be updated before calling.
- Grace periods come from Keycloak's **client policies** — a client profile carrying the
  `secret-rotation` executor, configured under `/admin/realms/{realm}/client-policies/profiles` and
  `/client-policies/policies`. Its exact executor configuration keys are not stated here because they
  have not been verified against a live server for this file; read the realm's current profiles back
  before relying on a grace period existing.
- With a grace period active, the previous secret is readable at
  `GET /admin/realms/{realm}/clients/{uuid}/client-secret/rotated`, and
  `DELETE` on that same path ends the grace period early. Only once every consumer is confirmed on
  the new secret.
- A **public** client has no secret to rotate. If the developer is hunting for one, the answer is
  that the client type is wrong for what they are building, not that the secret is missing.
- **Do not delete and re-create a client to change its secret.**

## Verify

```bash
curl -s "$BASE/admin/realms/$REALM/clients?clientId=my-web-app" -H "$H" \
  | jq '.[0] | {id, clientId, enabled, protocol, publicClient, standardFlowEnabled,
                serviceAccountsEnabled, redirectUris, webOrigins,
                pkce: .attributes["pkce.code.challenge.method"]}'
```

Expect `enabled: true`, `protocol: "openid-connect"`, `publicClient` matching the type chosen in
Step 1, both URI lists containing production **and** local-dev entries, and `pkce: "S256"` on a public
client. Confirm the discovery document is reachable and names the same realm:

```bash
curl -s "$BASE/realms/$REALM/.well-known/openid-configuration" | jq -r .issuer
```

Then have the developer run a real login in a real browser. A server-side or scripted check cannot
catch the `webOrigins` failure — it needs a browser to trigger CORS at all.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `401 Unauthorized` on every admin call, after some worked | `$ADMIN_TOKEN` expired — it lives for minutes | re-run the Step 0 token block |
| `403 Forbidden` on `POST`/`PUT` | the admin user lacks `manage-clients` in **that** realm | grant `realm-management` → `manage-clients` on the target realm, or use a full `master` admin |
| `409 Conflict` on `POST /clients` | the `clientId` is already taken — you are on Branch B, not A | switch to the read-merge-`PUT` in Step 3b |
| `404` on `GET`/`PUT /clients/{id}` | you passed the human-readable `clientId` where the UUID belongs | resolve the UUID first (Step 2); `clientId` ≠ `id` |
| `404` on `PUT`, and the path literally contains `null` | `jq -r '.[0].id'` on an empty array prints `null` | the client doesn't exist — guard the lookup, then go to Branch A |
| Client created, app still can't log in | it landed in `master` instead of the app's realm | check `$REALM`; delete the stray `master` client and create it in the right realm |
| The client's name / mappers / scopes vanished after an update | a partial `PUT` — omitted top-level fields are blanked | restore from a `GET` taken before the change if you have one; always read-merge-`PUT` |
| An attribute you removed from the body is still set | `attributes` merge, they don't replace | send that key explicitly as JSON `null` |
| `Invalid redirect_uri` on the Keycloak page | the URI the app sends doesn't exactly match a registered one | compare scheme/host/port/path character by character; check the app isn't appending a trailing slash |
| Login succeeds, then a CORS error on the token call | `webOrigins` missing or wrong | read-merge-`PUT` the correct origin, or `"+"` |
| `invalid_client` / "Client secret not provided" | the app is configured confidential but the client is `publicClient: true` (or the reverse) | make the app's config and `publicClient` agree; a public client sends no secret |
| `unauthorized_client` on a client-credentials call | `serviceAccountsEnabled` is `false` | read-merge-`PUT` it to `true`; a service account user is created behind it |
| Authorization code replay is possible on the SPA | `pkce.code.challenge.method` never set — Keycloak accepts PKCE but doesn't require it | set it to `S256` explicitly |
| Nothing works and `$ADMIN_TOKEN` was never obtainable | this is a Phase Two hosted deployment | wrong file — use `client-registration-mcp.md`; `rest` is not a fallback here |
