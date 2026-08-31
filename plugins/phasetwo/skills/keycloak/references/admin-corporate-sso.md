<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# Corporate SSO by email domain — via raw Admin REST

## What is actually being asked for

"I want corporate SSO login" decomposes into three requirements. Only the first is obvious,
and the third rules out the tempting answer:

1. **Broker the customer's identity provider** so their staff authenticate there, not here.
2. **Route to it automatically, by email domain** — a user typing `someone@customer.example`
   must never see your password form or a menu of providers.
3. **Leave everyone else alone** — your own staff, and every other customer, keep the login
   they already had.

Keycloak has an **Identity Provider Redirector** execution that sends users to a provider with
no prompt. It is not domain-based discovery: it forwards *everyone* (or only when the client
passes `kc_idp_hint`, which a plain browser login does not). It satisfies 1 and 2 and breaks 3.
Do not offer it as the answer to this request.

## Prerequisite: the `keycloak-orgs` extension

The mechanism is **[p2-inc `keycloak-orgs`](https://github.com/p2-inc/keycloak-orgs)** — a real,
installable extension (Elastic License 2.0), **not** stock Keycloak and **not** Keycloak's own
native in-core Organizations feature. Phase Two deliberately does not enable the native feature
([why](https://github.com/p2-inc/keycloak-orgs/blob/main/docs/note-keycloak-organizations-feature.md)).

Two consequences that trip up anyone who reaches for the native API first:

- Organizations live at **`/realms/{realm}/orgs`** — *not* `/admin/realms/{realm}/organizations`.
- There is **no `organizationsEnabled` realm switch**. That flag belongs to the native feature.
  Setting it does nothing for this extension; the extension is on as soon as the jar is deployed.

Confirm it's installed before anything else — a 404 here means the jar is missing, and every
stage below will fail in a more confusing way:

```bash
BASE=http://localhost:8080/auth       # include the relative path if one is configured
# Self-managed Keycloak: mint $ADMIN_TOKEN from the built-in admin-cli client in `master`
# (skip if you already have a token). Does NOT apply to Phase Two hosted deployments — there
# is no self-service admin REST credential of any kind there (confirmed with Phase Two).
# Without MCP, use the dashboard instead; raw REST is a dead end here, not a fallback.
ADMIN_TOKEN=$(curl -s -X POST "$BASE/realms/master/protocol/openid-connect/token" \
  -d client_id=admin-cli -d grant_type=password \
  -d username=<admin-user> -d password=<admin-password> \
  | jq -r .access_token)
H="Authorization: Bearer $ADMIN_TOKEN"
REALM=<realm>

curl -s -o /dev/null -w '%{http_code}\n' "$BASE/realms/$REALM/orgs" -H "$H"   # expect 200
```

## The mechanism: an org-linked IdP carrying its own domain list

Routing is done by the **`ext-auth-home-idp-discovery`** authenticator. It matches the domain of
the address typed on the login page against the **IdP's** config key
`home.idp.discovery.domains` — set for you when you link the IdP to an organization.

This is the single most misunderstood part of the feature:

> **Discovery does not read the organization's domain list, and does not care whether a domain is
> verified.** The org's verified domains are used by a *different*, optional authenticator
> (`ext-auth-org-id-verifier`, post-login only). Adding a domain to the org but not to the link
> leaves routing dead with nothing to indicate why.

Three things must all be true, and each fails silently on its own:

| Missing | Symptom |
|---|---|
| No `ext-auth-home-idp-discovery` execution in the bound browser flow | No domain-based routing exists at all |
| The IdP is created but **not linked** to an organization | The provider exists but routes nobody |
| The link carried no `domains` | The IdP is linked and hidden — matched users get no route *and* no button |

## Stage 1 — Broker the customer's identity provider

Use the connection details the customer's IT team supplied (endpoints, client ID, client
secret, email domain):

```bash
curl -s -X POST "$BASE/admin/realms/$REALM/identity-provider/instances" -H "$H" \
  -H 'Content-Type: application/json' -d '{
    "alias": "<idp-alias>",
    "displayName": "<Customer> SSO",
    "providerId": "oidc",
    "enabled": true,
    "trustEmail": true,
    "storeToken": false,
    "linkOnly": false,
    "config": {
      "clientId": "<client-id-from-customer>",
      "clientSecret": "<client-secret-from-customer>",
      "clientAuthMethod": "<client-auth-method>",
      "authorizationUrl": "<authorization-endpoint>",
      "tokenUrl": "<token-endpoint>",
      "userInfoUrl": "<userinfo-endpoint>",
      "jwksUrl": "<jwks-uri>",
      "issuer": "<issuer>",
      "defaultScope": "<scopes>",
      "useJwksUrl": "true"
    }
  }'
```

`trustEmail: true` matters here: without it, a brokered user is asked to verify an email the
customer already verified, stalling first login.

Don't bother setting `syncMode` or `postBrokerLoginFlowAlias` — Stage 3 overwrites both.

## Stage 2 — Create the organization

```bash
curl -s -X POST "$BASE/realms/$REALM/orgs" -H "$H" \
  -H 'Content-Type: application/json' -d '{
    "name": "<org-name>",
    "displayName": "<Customer>",
    "domains": ["<customer-email-domain>"]
  }'

# Get the org's id - the next step needs it.
curl -s "$BASE/realms/$REALM/orgs" -H "$H" \
  | jq -r --arg n "<org-name>" '.[] | select(.name==$n) | .id'
```

The representation accepts exactly `name`, `displayName`, `url`, `domains`, `attributes`
(plus a server-assigned `id` and `realm`). **`alias`, `enabled` and `description` do not exist
and are rejected with a 400** — the native-orgs payload shape does not work here.

**`domains` is an array of plain strings.** Passing the native shape
`[{"name": "acme.example", "verified": true}]` is the worst failure mode in this whole intent:
Jackson flattens the objects' keys and values into the string set, the call returns **201
Created**, and the org ends up holding garbage domains like
`["acme.example", "name", "true", "verified"]`.

## Stage 3 — Link the IdP to the organization, with the routing domains

This is the call that actually switches routing on:

```bash
curl -s -X POST "$BASE/realms/$REALM/orgs/<org-id>/idps/link" \
  -H "$H" -H 'Content-Type: application/json' -d '{
    "alias": "<idp-alias>",
    "domains": ["<customer-email-domain>"],
    "sync_mode": "FORCE",
    "post_broker_flow": "post org broker login"
  }'

# Verify the link took, and that the routing domains landed on the IdP.
curl -s "$BASE/admin/realms/$REALM/identity-provider/instances/<idp-alias>" -H "$H" \
  | jq '.config["home.idp.discovery.domains"], .config["home.idp.discovery.org"], .hideOnLogin'
```

Note the **`/link` suffix** and the **snake_case body keys** — `post_broker_flow` and `sync_mode`,
not their camelCase Java names. `POST .../idps` *without* `/link` is a different call that
**creates** a new org-owned IdP from a full `IdentityProviderRepresentation`; it will not adopt
one that already exists, and it rejects a bare alias string.

`domains` on the link is what writes `home.idp.discovery.domains`. **Omit it and routing never
happens** — the IdP is linked and hidden, so matched users see neither a redirect nor a button.

Only `alias` is required. The other three have defaults worth knowing:

| Field | Default when omitted |
|---|---|
| `sync_mode` | `FORCE` (realm attribute `_providerConfig.orgs.defaults.syncMode` overrides) |
| `post_broker_flow` | `post org broker login` (realm attribute `…defaults.postBrokerFlow` overrides) |
| `domains` | none written — routing stays dead |

**Creating an IdP does not associate it with any organization.** Without this call, discovery
will never find the IdP for that domain no matter how correct everything else is.

### What linking changes behind your back

`linkIdp` rewrites parts of the IdP you may have just set:

- **`hideOnLogin` is forced to `true`.** This is intended — the IdP is reached by domain match,
  not by a button, so it should not appear to everyone. Do not "fix" it back to `false`.
- `syncMode` and `postBrokerLoginFlowAlias` are overwritten from the link body or the defaults above.
- `home.idp.discovery.org` is set to the org id, and unless the realm has shared IdPs enabled
  (`_providerConfig.orgs.config.sharedIdps`), **other IdPs owned by that org are unlinked** —
  one active IdP per org is the default.

## Stage 4 — Domain verification (optional, and not what routing uses)

Verification exists for the `ext-auth-org-id-verifier` authenticator's `requireVerifiedDomain`
option, not for discovery. Skip this stage unless you're adding that check.

It is a **DNS TXT challenge**, not a boolean you can set:

```bash
# Read the challenge - recordKey / recordValue must be published as a TXT record.
curl -s "$BASE/realms/$REALM/orgs/<org-id>/domains" -H "$H" \
  | jq -r '.[] | "\(.domainName) \(.recordKey) \(.recordValue) verified=\(.verified)"'

# After the TXT record is live, ask the server to check it. 202 = accepted.
curl -s -X POST "$BASE/realms/$REALM/orgs/<org-id>/domains/<domain>/verify" -H "$H"
```

The server performs a real TXT lookup. There is no request that marks a domain verified without
one, and `"verified": true` in a create/update payload is not a field the representation has.

## Binding the discovery flow

The realm's built-in `browser` flow has no `ext-auth-home-idp-discovery` execution, so a flow
must be authored and bound. Author it from
[`../assets/home-idp.partial-import.json`](../assets/home-idp.partial-import.json) or
[`../assets/home-idp-with-orgs-check.partial-import.json`](../assets/home-idp-with-orgs-check.partial-import.json)
(the latter also treats the user as an organization member rather than only redirecting).
**Both assets set `forwardToLinkedIdp=true`** — the authenticator's factory default is `false`,
which silently prevents any redirect for a user who already has a federated identity.

**Keycloak's `partialImport` endpoint does not work for authentication flows** — it has no
handler for them, so an `authenticationFlows` array is silently ignored (HTTP 200, nothing
created, no error). The admin console's "Partial import" action and `kcadm.sh create
partialImport` hit that same endpoint and fail the same way. Two paths actually work:

| Path | Cost | Requires |
|---|---|---|
| `POST /admin/realms/{realm}/authentication-flow/import?force={bool}` — authors the flow *and* applies bindings (`browserFlowBinding`, `clientFlowBinding`, `idpFlowBindings`) in one call | One call | The [p2-inc keycloak-atomic-auth-flows](https://github.com/p2-inc/keycloak-atomic-auth-flows) extension installed |
| Manual sequence: `POST .../authentication/flows` → create each sub-flow → `POST .../executions/execution` per step → `PUT .../executions` to set requirements → attach authenticator config → bind | Many calls | Nothing beyond stock Admin REST |

Offer the extension when it isn't installed (it 404s clearly) — one jar collapses the whole
sequence — but the manual path is legitimate if the user can't add it. Note the extension
hash-prefixes the created alias, so read the real name back rather than assuming the asset's.

### Execution order is part of the configuration — the manual path loses it

Every execution here is `ALTERNATIVE`, which means **the first one that can answer wins and the
rest never run**. Order is not cosmetic; it *is* the behaviour. The two orderings below look
equally plausible in the admin console and only one works:

| `homeIdp` (top level) | `homeIdp forms` (sub-flow) |
|---|---|
| 1. `auth-cookie` — ALTERNATIVE | 1. `ext-auth-home-idp-discovery` — ALTERNATIVE |
| 2. `auth-spnego` — DISABLED | 2. `auth-password-form` — ALTERNATIVE |
| 3. `identity-provider-redirector` — ALTERNATIVE | |
| 4. `homeIdp forms` (sub-flow) — ALTERNATIVE | |

Two inversions are easy to produce and both fail silently:

- **`auth-password-form` before `ext-auth-home-idp-discovery`.** The password form always
  succeeds, so discovery never executes and **no domain is ever routed**. The realm looks fully
  configured and behaves as if the extension weren't installed. This is the single most common
  way this intent is built wrong.
- **`auth-cookie` last instead of first.** Users with a live SSO session get re-prompted
  instead of resuming.

**`POST .../executions/execution` and `.../executions/flow` append.** When the body omits
`priority`, the server assigns `last sibling's priority + 1`, so the order is simply the order
you made the calls in — and an execution remembered late (`auth-cookie` is the usual casualty)
lands at the bottom. Send `priority` explicitly on every call instead of relying on call order:

```bash
curl -s -X POST "$BASE/admin/realms/$REALM/authentication/flows/homeIdp%20forms/executions/execution" \
  -H "$H" -H 'Content-Type: application/json' \
  -d '{"provider": "ext-auth-home-idp-discovery", "priority": 20}'
```

`priority` in the body has only been honoured **since Keycloak 25** (added 2024-05-29). On 24
and older it is ignored and the call appends regardless — there, build in the intended order or
repair afterwards.

**Always read the order back.** No error is raised for a wrong order, so verify rather than
assume — `index` is the position within the level:

```bash
curl -s "$BASE/admin/realms/$REALM/authentication/flows/homeIdp/executions" -H "$H" \
  | jq -r '.[] | "\(.index) lvl=\(.level) pri=\(.priority) \(.requirement) \(.providerId // .displayName)"'
```

To repair an existing flow without rebuilding it, swap an execution with its adjacent sibling —
each call moves it exactly one position, so expect to repeat it:

```bash
curl -s -X POST "$BASE/admin/realms/$REALM/authentication/executions/<execution-id>/raise-priority" -H "$H"
# ...and lower-priority for the other direction.
```

The `authentication-flow/import` path and the assets carry their own `priority` values, so the
extension path gets this right for free. **This whole subsection is a hazard of the manual
sequence only.**

If binding separately (manual path, or an already-existing flow): set the realm representation's
`browserFlow` field (realm-wide) or the client's `authenticationFlowBindingOverrides` (single
client) — same mechanism as every other flow-binding intent in this router.

## Verify by logging in, not by reading configuration

Every setting here can be correct-looking and inert, and no endpoint reports routing — routing
is behaviour. Perform a real login twice:

| Submit on the login page | Expect |
|---|---|
| an address at the customer's routed domain | **no password field**; the browser is sent to the customer's IdP |
| an address at any other domain | **a password field**, and password login still completes |

The second row is not optional — it's what distinguishes correct domain discovery from a
redirector that hijacks every login.

[`../scripts/browser_login.py`](../scripts/browser_login.py) drives the whole round trip over
plain HTTP and prints where each step went:

```bash
python3 browser_login.py --realm acme --client acme-portal \
  --redirect-uri http://localhost:9999/callback \
  --username someone@customer.example --idp-username u --idp-password p
```

Two client-side details that otherwise cost an afternoon:

- Keycloak sets `AUTH_SESSION_ID` and `KC_RESTART` as `Secure; SameSite=None`. Browsers send
  them over `http://localhost` anyway (loopback is a secure context); most HTTP client libraries
  will not, and every form POST then returns `400` *"Cookie not found."* Clear the flag on each
  response (`cookie.secure = False` in Python `requests`).
- A user who has **never** federated and one who **already** has a federated identity are sent
  onward differently (an offered link versus an immediate redirect with `login_hint`). Test
  both, or a check passes on the first login and fails on the second.

Afterwards, a correctly federated user has a non-empty federated identity and **no** password
credential in your realm — hand-creating a local account with a matching email reproduces some
of the behavior while being the opposite of federation.

## Provider settings that bite

- **The redirect URI the customer must whitelist** is
  `{base}/realms/{realm}/broker/{alias}/endpoint` — it contains the alias, so choose the alias
  *before* asking them to whitelist anything.
- **`syncMode`** — the link defaults to `FORCE`, refreshing profile fields on every login. `IMPORT`
  copies them on first login only, which goes stale exactly when the customer's directory is
  authoritative.
- **`home.idp.discovery.matchSubdomains`** — set `"true"` on the IdP config to route
  `mail.acme.example` as well as `acme.example`. Defaults to `"false"`.

## Not organization *restriction*

This is an automatic redirect, not a membership gate. A user whose email domain matches no
organization falls through to the password fallback. "Only members of this organization may log
in at all" is a different, related mechanism — see the `admin:org-restrict-login` and
`admin:idp-org-restrict-login` intents.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `404` on `/realms/{realm}/orgs` | The `keycloak-orgs` extension is not deployed |
| `400` "Unrecognized field" creating an org | Native-orgs payload — drop `alias`, `enabled`, `description` |
| Org created `201` but domains are nonsense strings | `domains` was sent as objects; it is an array of plain strings |
| Matched domain still shows the password form | `auth-password-form` ordered **before** `ext-auth-home-idp-discovery`, no discovery execution in the bound flow at all, or `forwardToLinkedIdp` left at its `false` default |
| Everything looks configured but no domain ever routes | Execution order — read it back with `GET .../flows/{alias}/executions` before believing the console |
| Users with a live session get re-prompted for login | `auth-cookie` is not first in the top-level flow |
| Matched domain gets neither password nor route | The IdP was linked without `domains`, so it is hidden but unroutable |
| `404` "No IdP found with alias" on link | The IdP alias doesn't exist yet — create it first (Stage 1) |
| `400` "Cannot link disabled IdP" | The IdP has `enabled: false` |
| Linking a second IdP silently disables the first | Default one-IdP-per-org; enable `_providerConfig.orgs.config.sharedIdps` / `multipleIdps` |
| Domain never verifies | The TXT record isn't published, or not at the `recordKey` the API reports |
| `400` "Cookie not found" while scripting | `Secure` cookies not sent over http by the client |
| `invalid_redirect_uri` at the customer's provider | They whitelisted a different alias than the one created |
