<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# Restrict federated (IdP) login to members of one organization — via raw Admin REST

## What this is, and what it isn't

The user authenticates at an **external identity provider**, and only gets into your realm if
they belong to the organization the application asked for. Two things make this different from
`admin:org-restrict-login`, which gates a *local password* login:

- The gate runs **after** the IdP round-trip, so it lives on a third binding surface: the
  identity provider's own **`postBrokerLoginFlowAlias`** — not the realm's `browserFlow`, not a
  client override.
- Membership is normally *established* by the login itself: `ext-auth-org-add-user` adds the
  arriving user to the organization that **owns** the IdP. The gate then discriminates between
  that organization and any other.

**The trap that makes this silently do nothing**: Keycloak ships a stock post-broker flow, and
it does **not** contain `ext-select-org`. Bind that one and `account_hint` is never evaluated —
every brokered login succeeds and the configuration looks complete.

**The second trap**: `ext-auth-org-note` and `ext-auth-org-add-user` both no-op unless the IdP
is *linked* to an organization, so the flow can be bound correctly and still gate nothing.

## Check the organizations extension is actually installed, first

Everything here — organizations, membership, and all four `ext-*` authenticators — comes from
the **[p2-inc `keycloak-orgs`](https://github.com/p2-inc/keycloak-orgs) extension**. It is not
stock Keycloak, and it is **not** Keycloak's native in-core Organizations feature: different
REST surface (`/realms/{realm}/orgs`, no `/admin` prefix), and `ext-select-org` reads the
extension's, not the native one.

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
IDP=<idp-alias>

# If this 404s, the extension isn't installed - stop; there is no fallback.
curl -s "$BASE/realms/$REALM/orgs" -H "$H"
```

## Stage 1 — Ask: match the organization by NAME or by ID?

**Ask explicitly.** `account_hint` can carry either, and `ext-select-org`'s `match_by_org_name`
decides which is read — whatever the application actually sends is the answer.

| The application sends… | `match_by_org_name` |
|---|---|
| The organization's **name** (`engineering`) | `"true"` |
| The organization's **ID** (UUID) | `"false"` |

The bundled asset [`../assets/post-org-broker-login-select-organization.partial-import.json`](../assets/post-org-broker-login-select-organization.partial-import.json)
ships `"true"`. An application that never learns a server-generated UUID can only send a name.

## Stage 2 — Organizations, IdP, and the link that makes it all work

```bash
# 1. The organization that will OWN the IdP (plus any others the app may name).
#    Note: NO `enabled` field - the extension's Organization representation rejects
#    unknown fields outright with a 400.
curl -s -X POST "$BASE/realms/$REALM/orgs" -H "$H" \
  -H 'Content-Type: application/json' -d '{"name":"engineering"}'
curl -s -X POST "$BASE/realms/$REALM/orgs" -H "$H" \
  -H 'Content-Type: application/json' -d '{"name":"finance"}'

ORG_ID=$(curl -s "$BASE/realms/$REALM/orgs" -H "$H" \
  | jq -r '.[] | select(.name=="engineering") | .id')

# 2. Broker the customer's provider, using the details their IT team supplied.
curl -s -X POST "$BASE/admin/realms/$REALM/identity-provider/instances" -H "$H" \
  -H 'Content-Type: application/json' -d '{
    "alias": "'"$IDP"'", "displayName": "Partner SSO", "providerId": "oidc",
    "enabled": true, "trustEmail": true, "storeToken": false, "linkOnly": false,
    "config": {
      "clientId": "<client-id>", "clientSecret": "<client-secret>",
      "clientAuthMethod": "<client-auth-method>",
      "authorizationUrl": "<authorization-endpoint>", "tokenUrl": "<token-endpoint>",
      "userInfoUrl": "<userinfo-endpoint>", "jwksUrl": "<jwks-uri>", "issuer": "<issuer>",
      "defaultScope": "openid profile email", "syncMode": "IMPORT", "useJwksUrl": "true"
    }}'

# 3. THE STEP THAT MAKES IT ORGANIZATION-OWNED. Without it the post-broker
#    authenticators have nothing to act on and the gate is inert.
curl -s -X POST "$BASE/realms/$REALM/orgs/$ORG_ID/idps/link" -H "$H" \
  -H 'Content-Type: application/json' -d '{"alias":"'"$IDP"'"}'

# Verify the link rather than assuming it from a 2xx on the create call.
curl -s "$BASE/realms/$REALM/orgs/$ORG_ID/idps" -H "$H" | jq -r '.[].alias'
```

## Stage 3 — Author the post-broker flow, and bind it to the IdP

The flow's executions, in order — the shape the bundled asset produces:

| Authenticator | Requirement | Does what |
|---|---|---|
| `ext-auth-org-note` | REQUIRED | Sets `org_id` session notes when an org-owned IdP was used |
| `ext-auth-org-id-verifier` | DISABLED | Off in this shape |
| `ext-auth-validate-idp` | REQUIRED | Validates newly created organization IdPs |
| `ext-auth-org-add-user` | REQUIRED | **Adds the arriving user to the IdP's organization** |
| `ext-select-org` (config `match-by-org-name`) | REQUIRED | **The gate** |

| Path | Cost | Requires |
|---|---|---|
| `POST /admin/realms/{realm}/authentication-flow/import?force={bool}` — authors the flow **and** binds it to the IdP in one call | **One call** | The [p2-inc keycloak-atomic-auth-flows](https://github.com/p2-inc/keycloak-atomic-auth-flows) extension |
| Manual sequence, then set `postBrokerLoginFlowAlias` on the IdP | Many calls | Nothing beyond stock Admin REST |
| ~~`POST /admin/realms/{realm}/partialImport`~~ | — | **Does not work.** No handler for authentication flows: HTTP 200, `added: 0`, no error. |

**Atomic path** — offer the extension when it isn't installed (it 404s clearly):

```bash
# Take the asset, STRIP ifResourceExists (a partialImport field - AuthenticationFlowPayload
# rejects unknown fields with a 400; use ?force= instead), and add the IdP binding.
jq --arg idp "$IDP" '
    del(.ifResourceExists)
    | .idpFlowBindings = [{alias: $idp, postLoginFlowBinding: .authenticationFlows[0].alias}]
  ' post-org-broker-login-select-organization.partial-import.json > /tmp/flow.json

curl -s -X POST "$BASE/admin/realms/$REALM/authentication-flow/import?force=false" \
  -H "$H" -H 'Content-Type: application/json' --data-binary @/tmp/flow.json

# The extension hash-prefixes BOTH the flow it creates and the binding value, so they line
# up automatically - pass the ORIGINAL alias, then read the real one back off the IdP.
curl -s "$BASE/admin/realms/$REALM/identity-provider/instances/$IDP" -H "$H" \
  | jq -r '.postBrokerLoginFlowAlias'
```

Payload details, each a 400 if wrong (verified against the extension's source):
- The IdP binding field is **`postLoginFlowBinding`** — a *flow-alias string*, not
  `postBrokerLoginFlowAlias`, and not a boolean.
- The *IdP* alias inside `idpFlowBindings` is passed through **unprefixed**; only the flow
  binding value gets the hash prefix.

**Manual path** — create the flow, add each execution above in order with its requirement,
attach the `match-by-org-name` config to the `ext-select-org` execution, then bind by setting
`postBrokerLoginFlowAlias` on the IdP representation and PUTting it back:

```bash
curl -s "$BASE/admin/realms/$REALM/identity-provider/instances/$IDP" -H "$H" > /tmp/idp.json
# set "postBrokerLoginFlowAlias": "<your flow alias>" in /tmp/idp.json
curl -s -X PUT "$BASE/admin/realms/$REALM/identity-provider/instances/$IDP" -H "$H" \
  -H 'Content-Type: application/json' --data-binary @/tmp/idp.json
```

## Stage 4 — Verify by logging in, not by reading configuration

Nothing here reports whether the gate is live, and the obvious check — "a valid user with valid
credentials gets in" — passes even when membership is never inspected. Drive three real logins,
forcing the provider with `kc_idp_hint` so this tests the post-broker gate specifically:

```
$BASE/realms/$REALM/protocol/openid-connect/auth
  ?client_id=<client>&response_type=code&scope=openid
  &redirect_uri=<redirect>&state=<state>
  &kc_idp_hint=$IDP&account_hint=<org>
```

| `account_hint` | Expect |
|---|---|
| the organization owning the IdP | login completes with an authorization code |
| a **different real** organization the user isn't in | rejected, no code |
| an organization that doesn't exist | rejected, no code |

The middle row is what actually proves membership is checked — a flow that merely requires
*some* `account_hint` passes the first and third and fails the second.

If scripting: Keycloak marks `AUTH_SESSION_ID` / `KC_RESTART` as `Secure; SameSite=None`. A
browser sends them over `http://localhost` anyway (loopback is a secure context); most HTTP
clients will not, so an auto-following redirect chain silently loses the session and dead-ends
at `/broker/{alias}/login`. Follow redirects manually and clear the flag after every response
(`cookie.secure = False` in Python `requests`).

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| Every brokered login succeeds regardless of `account_hint` | The bound post-broker flow has no `ext-select-org` execution (most likely Keycloak's stock one) |
| Gate never triggers, no membership created | The IdP isn't linked to an organization, so `ext-auth-org-add-user`/`ext-auth-org-note` no-op |
| `account_hint` names a real org but never matches | `match_by_org_name` disagrees with what the app sends (name vs. ID) |
| 400 `Unrecognized field "ifResourceExists"` | That field belongs to `partialImport`; strip it, use `?force=` |
| 400 `Unrecognized field "postBrokerLoginFlowAlias"` | The atomic payload's field is `postLoginFlowBinding` |
| 400 `Unrecognized field "enabled"` on org create | The extension's Organization representation has no such field |
| Redirect chain dead-ends at `/broker/{alias}/login` | `Secure` cookies not sent over http by the client |
| `partialImport` returned 200 but no flow exists | That endpoint ignores authentication flows entirely |
