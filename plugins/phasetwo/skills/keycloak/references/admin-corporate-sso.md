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

Keycloak 26.8 moved the *native* feature's domain routing onto the organization's domain
(`identityProviderAlias`, `autoRedirect`). None of that applies to this extension. This path was
re-verified, unchanged, on Phase Two's 26.8.2 image.

Confirm it's installed before anything else — a 404 here means the jar is missing, and every
stage below will fail in a more confusing way:

```bash
BASE=http://localhost:8080/auth       # include the relative path if one is configured
# Self-managed Keycloak: <admin-access-token> is a `master` admin access token the developer gives you.
# Does NOT apply to Phase Two hosted deployments — there
# is no self-service admin REST credential of any kind there (confirmed with Phase Two).
# Without MCP, use the dashboard instead; raw REST is a dead end here, not a fallback.
H="Authorization: Bearer <admin-access-token>"   # token from the developer, never their password — SKILL.md "Admin token"
REALM=<realm>

curl -s -o /dev/null -w '%{http_code}\n' "$BASE/realms/$REALM/orgs" -H "$H"   # expect 200
```

## The mechanism: the organization's domains, and the IdP linked to it

Routing is done by the **`ext-auth-home-idp-discovery`** authenticator. It takes the domain of
the address typed on the login page and finds the organization whose **own domain list** holds
it. It then forwards to that organization's linked, enabled IdP: the IdP whose config key
`home.idp.discovery.org` names the org, which linking sets for you.

This is the single most misunderstood part of the feature:

> **Discovery reads the organization's domain list, not the link's.** The `domains` sent when
> linking land on the IdP as `home.idp.discovery.domains`. Discovery reads that list only when
> the realm allows several IdPs per organization (`_providerConfig.orgs.config.multipleIdps`), and
> then only to choose among them. An organization that does not hold the domain routes nobody,
> whatever the link carried. Verification does not matter either, unless the discovery
> execution's own config sets `requireVerifiedDomain` to `true`. It defaults to `false`, and the
> bundled assets leave it off.

Measured on Phase Two's Keycloak 26.8.2 image (keycloak-orgs 0.199), all with unverified
domains:

- An org without domains, linked with `domains`, did not route.
- Adding the domain to that org made it route.
- An org holding the domain, linked without `domains`, routed.

Three things must all be true, and each fails silently on its own:

| Missing | Symptom |
|---|---|
| No `ext-auth-home-idp-discovery` execution in the bound browser flow | No domain-based routing exists at all |
| The organization does not hold the customer's email domain | Nothing matches, even if the link carried the domain |
| The IdP is created but **not linked** to the organization | The organization has no IdP to forward to |

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

**These are the domains discovery matches.** Put the customer's email domain here. Passing it only
on the link in Stage 3 routes nobody. Since keycloak-orgs 0.199 they also gate first login: the
realm's `first broker login` flow carries a REQUIRED `ext-auth-org-domain-fbl-verifier`
(GHSA-gvcc-4vw2-6wvr), so a first login through an IdP linked to an organization stops on "Valid
identity email domain not found." unless the email the IdP sends is at one of that organization's
domains.

## Stage 3 — Link the IdP to the organization

This is the call that gives the organization an IdP to route to:

```bash
curl -s -X POST "$BASE/realms/$REALM/orgs/<org-id>/idps/link" \
  -H "$H" -H 'Content-Type: application/json' -d '{
    "alias": "<idp-alias>",
    "domains": ["<customer-email-domain>"],
    "sync_mode": "FORCE",
    "post_broker_flow": "post org broker login"
  }'

# Verify the link took: home.idp.discovery.org is the org id.
curl -s "$BASE/admin/realms/$REALM/identity-provider/instances/<idp-alias>" -H "$H" \
  | jq '.config["home.idp.discovery.org"], .config["home.idp.discovery.domains"], .hideOnLogin'
```

Note the **`/link` suffix** and the **snake_case body keys** — `post_broker_flow` and `sync_mode`,
not their camelCase Java names. `POST .../idps` *without* `/link` is a different call that
**creates** a new org-owned IdP from a full `IdentityProviderRepresentation`; it will not adopt
one that already exists, and it rejects a bare alias string.

`domains` on the link writes `home.idp.discovery.domains` on the IdP. Discovery reads that list
only when the realm allows several IdPs per organization
(`_providerConfig.orgs.config.multipleIdps`); otherwise it has no effect. Passing the same domain
as the org costs nothing, and routing keeps working if multiple IdPs are switched on later.

Only `alias` is required. The other three have defaults worth knowing:

| Field | Default when omitted |
|---|---|
| `sync_mode` | `FORCE` (realm attribute `_providerConfig.orgs.defaults.syncMode` overrides) |
| `post_broker_flow` | `post org broker login` (realm attribute `…defaults.postBrokerFlow` overrides) |
| `domains` | none written; this only matters when the realm allows multiple IdPs per org |

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

## Stage 4 — Domain verification (optional; routing ignores it by default)

Verification matters only where a `requireVerifiedDomain` option is switched on. That option
exists on the discovery execution's config (off by default, and off in the bundled assets) and
on the `ext-auth-org-id-verifier` authenticator. Skip this stage unless you turn one on.

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
Both assets set `forwardToLinkedIdp=true`. It decides only whether discovery consults the user's
existing federated links. When it is on, a provider the user is already linked to wins over the
first provider their domain matches, and a linked user is forwarded to it even when their domain
matches no organization. With one provider per organization, and users at the organization's
domains, it changes nothing: measured on Phase Two's 26.8.2 image (keycloak-orgs 0.199),
first-time and returning users were forwarded alike at its default of `false`.

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
rest never run**. Order is not cosmetic; it *is* the behaviour. Build it in the asset's order:

| `homeIdp` (top level) | `homeIdp forms` (sub-flow) |
|---|---|
| 1. `auth-cookie` — ALTERNATIVE | 1. `ext-auth-home-idp-discovery` — ALTERNATIVE |
| 2. `auth-spnego` — DISABLED | 2. `auth-password-form` — ALTERNATIVE |
| 3. `identity-provider-redirector` — ALTERNATIVE | |
| 4. `homeIdp forms` (sub-flow) — ALTERNATIVE | |

- **`auth-cookie` last instead of first** fails silently: users with a live SSO session get
  re-prompted instead of resuming.
- **`auth-password-form` before `ext-auth-home-idp-discovery`** still routes. The password form
  is skipped until someone has been identified, so discovery's username form comes first either
  way (measured on Phase Two's 26.8.2 image). Keep the asset's order anyway.

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

```bash
BASE=http://localhost:8080/auth; REALM=<realm>; JAR=$(mktemp)
form_action() { grep -o 'action="[^"]*"' | head -1 | sed -e 's/^action="//' -e 's/"$//' -e 's/&amp;/\&/g'; }
login_page() {   # fresh login page for this client → prints the form's POST URL
  curl -s -G -c "$JAR" -b "$JAR" "$BASE/realms/$REALM/protocol/openid-connect/auth" \
    --data-urlencode "client_id=<client-id>" --data-urlencode "redirect_uri=<app-redirect-uri>" \
    -d response_type=code -d scope=openid \
    -d code_challenge_method=S256 -d code_challenge=E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM \
    | form_action   # a fixed PKCE challenge is fine: the code is never redeemed
}
# Routed domain: expect a 302 whose redirect URL is the customer's IdP (or a broker endpoint
# that leads there), not a page with a password field
curl -s -c "$JAR" -b "$JAR" -o /dev/null -w '%{http_code} %{redirect_url}\n' \
  --data-urlencode "username=someone@customer.example" "$(login_page)"
# Any other domain: expect 200 and a password field (prints 1 or more)
curl -s -c "$JAR" -b "$JAR" --data-urlencode "username=someone@other.example" \
  "$(login_page)" | grep -c 'type="password"'
```

This proves the routing. Completing the IdP login and the password login needs real
credentials, so the developer does that part in a browser. Don't ask them for a password to
script it. **Never set, reset or change a user's password, and never impersonate a user, to
make a test login complete.** That rewrites the account you are verifying: the internal user's
real password stops working, which is exactly the regression this check exists to catch. With
no test credential, stop after the routing check and hand the developer the two logins to
finish by hand.

Two client-side details that otherwise cost an afternoon:

- Keycloak sets `AUTH_SESSION_ID` and `KC_RESTART` as `Secure; SameSite=None`. Browsers and
  `curl` send them over `http://localhost` (loopback counts as secure), but not over plain
  `http://` to any other host, and every form POST then returns `400` *"Cookie not found."* Use
  `https` or `localhost`; some other HTTP clients need the Secure flag cleared on each response.
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
| Matched domain still shows the password form | No `ext-auth-home-idp-discovery` execution in the flow in effect: the stock `browser` flow has none. Read back the realm's `browserFlow` (or the client's `authenticationFlowBindingOverrides`), then `GET .../flows/{alias}/executions`, before believing the console |
| Users with a live session get re-prompted for login | `auth-cookie` is not first in the top-level flow |
| A domain never routes although the IdP is linked | The organization does not hold that domain. The link's `domains` alone do not route. Add the domain to the org: `GET /realms/{realm}/orgs/{org-id}`, add it to `domains`, `PUT` the org back |
| `404` "No IdP found with alias" on link | The IdP alias doesn't exist yet — create it first (Stage 1) |
| `400` "Cannot link disabled IdP" | The IdP has `enabled: false` |
| Linking a second IdP silently disables the first | Default one-IdP-per-org; enable `_providerConfig.orgs.config.sharedIdps` / `multipleIdps` |
| Domain never verifies | The TXT record isn't published, or not at the `recordKey` the API reports |
| `400` "Cookie not found" while scripting | `Secure` cookies not sent over http by the client |
| `invalid_redirect_uri` at the customer's provider | They whitelisted a different alias than the one created |
