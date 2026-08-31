<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# Restrict login to members of one organization — via raw Admin REST

## What this is, and what it isn't

This is a **membership gate**: only someone who is already a member of a specific organization
can complete login. It is not domain-based routing to a corporate IdP — that sends a user
somewhere to authenticate but never restricts *who* may log in.

**The trap**: binding an org-aware flow does **not**, by itself, force every plain
username/password login to require organization membership. The org-selection/membership check
only runs when the authorization request carries **`prompt=select_account`** or
**`account_hint=<value>`** — a client has to actually send one of those. A login with neither
skips the check entirely and behaves like an ordinary login. If the goal is "every login to this
client must be gated," confirm the client actually sends one of those parameters; binding the
flow is necessary but not sufficient.

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
```

## Prerequisite: the keycloak-orgs extension

Organizations here come from the **[p2-inc `keycloak-orgs`](https://github.com/p2-inc/keycloak-orgs)**
extension, not Keycloak's own native Organizations feature (Phase Two deliberately does not use
the native one). Its REST surface is mounted at `/realms/{realm}/orgs` — note that's *not* under
`/admin`. If that 404s, the extension isn't installed and nothing below will work; say so rather
than falling back to the native organizations API, which is a different, incompatible mechanism.

## Stage 1 — Ask: match the organization by NAME or by ID?

**Ask this explicitly — don't guess.** `account_hint` can carry either an organization's name or
its ID, and the flow must be configured for exactly one interpretation via the `ext-select-org`
authenticator's `match_by_org_name` config key:

| The application will send… | Set `match_by_org_name` to | Asset |
|---|---|---|
| The organization's **name** (human-readable, e.g. `engineering`) | `"true"` | [`assets/org-browser-flow-by-org-name.partial-import.json`](../assets/org-browser-flow-by-org-name.partial-import.json) |
| The organization's **ID** (UUID) | `"false"` | [`assets/org-browser-flow-by-org-id.partial-import.json`](../assets/org-browser-flow-by-org-id.partial-import.json) |

If the application sends a fixed human-readable string it chose itself, it can only be matching by
NAME — it has no way to know a server-generated UUID. Pick accordingly.

## Stage 2 — Create the organization

```bash
curl -s -X POST "$BASE/realms/$REALM/orgs" -H "$H" \
  -H 'Content-Type: application/json' -d '{"name":"<org-name>"}'
```

The representation accepts `name`, `displayName`, `url`, `domains`, `attributes` — **there is no
`enabled` field**; sending one is rejected with a 400 naming the unrecognized field. Read the new
organization's id from the `Location` header, or list `/realms/$REALM/orgs` and match on name.

## Stage 3 — Add the members

```bash
# Find the user's id first.
curl -s "$BASE/admin/realms/$REALM/users?username=<username>&exact=true" -H "$H"

# PUT (not POST) - the body is empty; membership is expressed by the path.
curl -s -X PUT "$BASE/realms/$REALM/orgs/<org-id>/members/<user-id>" -H "$H"

# Verify: 204 means this user IS a member, 404 means they are not.
curl -s -o /dev/null -w '%{http_code}\n' \
  "$BASE/realms/$REALM/orgs/<org-id>/members/<user-id>" -H "$H"
```

Only add the users who should be let in. Everyone else being *absent* is what the gate actually
enforces — verify a non-member is genuinely not a member rather than assuming.

## Stage 4 — Author the flow, and bind it

**Check first — you probably don't need to author anything.** A Keycloak running keycloak-orgs
usually ships a built-in **`Org Browser Flow`** that *already contains* the `ext-select-org`
execution:

```bash
curl -s "$BASE/admin/realms/$REALM/authentication/flows" -H "$H" | jq -r '.[].alias'
curl -s "$BASE/admin/realms/$REALM/authentication/flows/Org%20Browser%20Flow/executions" -H "$H"
```

If it's there, the whole job is: point its `ext-select-org` execution's config at the right
`match_by_org_name` value (see the config call in Path B step 4, or PUT the existing config), then
bind it (below). Skip the rest of this stage entirely. Only author a flow if no flow with an
`ext-select-org` execution exists.

**Keycloak's `partialImport` endpoint does not work for authentication flows.** It has no handler
for them at all (only clients, roles, identity providers, IdP mappers, groups and users), so an
`authenticationFlows` array sent to it is **silently ignored** — HTTP 200, `added: 0`, no error.
The admin console's "Partial import" action and `kcadm.sh create partialImport` hit that same
endpoint and fail the same way. (The bundled assets are named `*.partial-import.json` for
historical reasons; their contents are correct, the name is not.)

Two paths that do work:

### Path A — the atomic-flows extension (one call, authors *and* binds)

If [p2-inc keycloak-atomic-auth-flows](https://github.com/p2-inc/keycloak-atomic-auth-flows) is
installed:

```bash
# Body: the asset's authenticationFlows + authenticatorConfig arrays, plus the binding.
curl -s -X POST "$BASE/admin/realms/$REALM/authentication-flow/import" -H "$H" \
  -H 'Content-Type: application/json' -d '{
    "authenticationFlows": [ ...from the asset... ],
    "authenticatorConfig": [ ...from the asset... ],
    "browserFlowBinding": "Org Browser Flow by Org Name"
  }'
```

Also accepts `clientFlowBinding` (`{clientId, browserFlowBinding, directFlowBinding}`) and
`idpFlowBindings` (`[{alias, firstLoginFlowBinding, postLoginFlowBinding}]`). The asset's own
`ifResourceExists` field is not part of this payload and is ignored.

**It hash-prefixes every alias.** The created flow is named e.g.
`8esLlLB3D3YqVg-Org Browser Flow by Org Name`, not what the asset says — read the real alias back
from the response or from the realm's `browserFlow` field. That hash is also its idempotency: an
identical re-import returns **409** and creates nothing; `?force=true` replaces in place instead of
duplicating.

If this 404s, the extension isn't installed — worth offering, since it collapses Path B's whole
sequence into one call.

### Path B — the manual sequence (stock Admin REST, many calls)

```bash
# 1. Create the top-level flow, then each sub-flow the asset defines.
curl -s -X POST "$BASE/admin/realms/$REALM/authentication/flows" -H "$H" \
  -H 'Content-Type: application/json' \
  -d '{"alias":"<flow>","providerId":"basic-flow","topLevel":true,"builtIn":false}'

# 2. Add each execution to its flow. These calls APPEND - with no "priority" the server
#    assigns (last sibling + 1), so order is just call order. Send it explicitly.
curl -s -X POST "$BASE/admin/realms/$REALM/authentication/flows/<urlencoded-flow>/executions/execution" \
  -H "$H" -H 'Content-Type: application/json' -d '{"provider":"ext-select-org","priority":20}'

# 3. List executions to get each id, then PUT each one's requirement.
curl -s "$BASE/admin/realms/$REALM/authentication/flows/<urlencoded-flow>/executions" -H "$H"
curl -s -X PUT "$BASE/admin/realms/$REALM/authentication/flows/<urlencoded-flow>/executions" \
  -H "$H" -H 'Content-Type: application/json' -d '{"id":"<exec-id>","requirement":"REQUIRED","priority":<its current priority>}'

# 4. Attach the authenticator config to the ext-select-org execution.
curl -s -X POST "$BASE/admin/realms/$REALM/authentication/executions/<exec-id>/config" \
  -H "$H" -H 'Content-Type: application/json' \
  -d '{"alias":"match-by-org-name","config":{"match_by_org_name":"true"}}'

# 5. Bind it: realm-wide via the realm representation's browserFlow field (read-modify-write),
#    or per-client via the client's authenticationFlowBindingOverrides.
```

Note `/executions` returns the whole tree recursively (level 0 sub-flows, level 1+ their steps),
which is also how you verify the result.

**Order is load-bearing here, and nothing reports getting it wrong.** The asset's shape is three
ALTERNATIVE sub-flows off the top level, each ending in `ext-select-org`:

| Flow | Order | Requirement |
|---|---|---|
| top level | 1. Cookies sub-flow → 2. IDP sub-flow → 3. Forms sub-flow | ALTERNATIVE each |
| Cookies sub-flow | `auth-cookie` → `ext-select-org` | REQUIRED each |
| IDP sub-flow | `identity-provider-redirector` → `ext-select-org` | REQUIRED each |
| Forms sub-flow | `auth-username-password-form` → *conditional OTP* → `ext-select-org` | REQUIRED / CONDITIONAL / REQUIRED |

`ext-select-org` **must come last inside each sub-flow** — it reads the identity established by
the step before it. Put it first and it evaluates with no user, so the gate silently admits
everyone: the exact opposite of the intent, with no error anywhere. Equally, the Forms sub-flow
landing ahead of the Cookies sub-flow re-prompts users who already hold a session.

Read the order back and check it against the table before declaring this done:

```bash
curl -s "$BASE/admin/realms/$REALM/authentication/flows/<urlencoded-flow>/executions" -H "$H" \
  | jq -r '.[] | "\(.index) lvl=\(.level) pri=\(.priority) \(.requirement) \(.providerId // .displayName)"'
```

`priority` in the body is honoured only from **Keycloak 25** onward (added 2024-05-29); on 24 and
older it is ignored and calls append regardless. There, add executions in the intended order and
repair with `POST .../authentication/executions/<exec-id>/raise-priority`, which swaps an
execution with one adjacent sibling per call. Path A carries the asset's own `priority` values, so
it gets ordering right for free — this is a Path B hazard only.

## Verify by logging in, not by reading configuration

Nothing here reports whether the gate is active — behavior only shows up in a real login. Drive
three, using `account_hint` on the authorization request exactly as the application will:

| Attempt | Expect |
|---|---|
| A member, with the correct `account_hint` | Completes, landing at the redirect URI with an authorization code |
| A member, with an `account_hint` matching no real organization | Rejected — no code |
| A **non-member**, with the correct `account_hint` | Rejected — no code |

The third is the one that actually proves membership is being checked: a flow that merely requires
*some* `account_hint` value passes the first two while failing the real requirement.

If scripting this: Keycloak's `AUTH_SESSION_ID`/`KC_RESTART` cookies are `Secure; SameSite=None`.
Browsers send them over `http://localhost` anyway (loopback is a secure context); most HTTP client
libraries won't, and every form POST then fails with `400 "Cookie not found."` Clear the flag on
each response (`cookie.secure = False` in Python `requests`).

## Troubleshooting

| Symptom | Cause |
|---|---|
| Bound the flow, but logins are unaffected either way | The client isn't sending `account_hint`/`prompt=select_account` — expected, not a bug |
| `partialImport` returned 200 but no flow exists | That endpoint ignores authentication flows entirely; use Path A or B |
| Everyone gets in regardless of `account_hint` | The bound flow has no `ext-select-org` execution, or it isn't REQUIRED |
| Nobody gets in, including real members | `match_by_org_name` disagrees with what the app sends (name vs ID), or the member was never actually added |
| 400 "Unrecognized field 'enabled'" creating an organization | The keycloak-orgs Organization representation has no `enabled` field |
| The imported flow isn't named what the asset says | Path A hash-prefixes aliases — read the real one back |
