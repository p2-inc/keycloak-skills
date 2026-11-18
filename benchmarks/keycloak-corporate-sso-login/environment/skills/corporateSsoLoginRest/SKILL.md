---
name: corporateSsoLoginRest
description: >-
  Set up corporate SSO / enterprise SSO on a self-managed Keycloak — send a user to their own
  company's identity provider based on the domain of the email address they type, while everyone
  else keeps password login — using the Admin REST API only (no MCP server involved). Use this
  whenever someone says "I want corporate SSO login", "we need enterprise SSO", "SSO for our
  customer", "let our customer log in with their company account", "log in with my company's SSO
  automatically", "redirect to my corporate IdP", "authenticate to my corporate IdP", "home realm
  discovery", "IdP discovery by email domain", "onboard an enterprise customer's SSO" — even if
  they only say "corporate SSO". Covers the organization + linked-IdP + routed-domain mechanism
  that performs the discovery (Keycloak 26.8+), why an identity-provider-redirector execution is
  the wrong answer, and how to verify the routing by actually logging in.
---

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

```bash
BASE=http://localhost:8080/auth       # include the relative path if one is configured
H="Authorization: Bearer $ADMIN_TOKEN"
REALM=<realm>
```

## The mechanism: organizations, not the flow editor

Keycloak has exactly one built-in way to route by email domain, and it lives in the
**organizations** feature, not the authentication-flow editor where someone would look for it.
Four things must all be true, and each fails silently on its own:

| Missing | Symptom |
|---|---|
| The realm's organization support isn't switched on | No domain-based routing exists at all |
| No organization holds the customer's email domain | Discovery has nothing to match |
| The IdP is created but **not linked** to the organization | The domain cannot be routed to it (Stage 5 is refused with a 400) |
| The domain is not routed to the IdP **with auto-redirect** | The customer's staff get your password form with an SSO button beside it |

**Check the server version first** (`GET $BASE/admin/serverinfo` → `.systemInfo.version`).
Keycloak 26.8.0 moved routing onto the organization's domain
([upgrading guide](https://www.keycloak.org/docs/latest/upgrading/index.html), "Organization
identity providers now support many-to-many linking"). Guidance written for 26.7 and older sets
`kc.org.domain` and `kc.org.broker.redirect.mode.email-matches` on the IdP's config instead. 26.8
accepts that write and silently drops both keys.

Whether a domain is marked `verified` does not affect any of this. Measured on 26.0.7 and
26.8.2: an unverified domain routes exactly like a verified one.

## Stage 1 — Switch on organization support (a realm-representation PUT)

```bash
curl -s "$BASE/admin/realms/$REALM" -H "$H" > /tmp/realm.json
# set "organizationsEnabled": true in /tmp/realm.json, then PUT it back
curl -s -X PUT "$BASE/admin/realms/$REALM" -H "$H" \
  -H 'Content-Type: application/json' --data-binary @/tmp/realm.json

# Confirm it stuck - a realm PUT that omits fields resets them, so verify rather than assume.
curl -s "$BASE/admin/realms/$REALM" -H "$H" | jq '.organizationsEnabled'
```

## Stage 2 — Broker the customer's identity provider

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
      "syncMode": "IMPORT",
      "useJwksUrl": "true"
    }
  }'
```

`trustEmail: true` matters here: without it, a brokered user is asked to verify an email the
customer already verified, stalling first login.

## Stage 3 — Create the organization, holding the customer's domain

```bash
curl -s -X POST "$BASE/admin/realms/$REALM/organizations" -H "$H" \
  -H 'Content-Type: application/json' -d '{
    "name": "<org-name>",
    "alias": "<org-name>",
    "enabled": true,
    "description": "<Customer> - federated enterprise customer",
    "domains": [{"name": "<customer-email-domain>"}]
  }'

# Get the org's id - the next step needs it.
curl -s "$BASE/admin/realms/$REALM/organizations" -H "$H" \
  | jq -r --arg n "<org-name>" '.[] | select(.name==$n) | .id'
```

Don't put `identityProviderAlias` on the domain yet. Routing a domain to an IdP the
organization isn't linked to is refused with a 400 ("Identity provider '…' is not associated with
organization …"), so routing is Stage 5, after the link.

## Stage 4 — Link the IdP to the organization

```bash
# The body is a bare JSON STRING holding the provider alias, not an object.
curl -s -X POST "$BASE/admin/realms/$REALM/organizations/<org-id>/identity-providers" \
  -H "$H" -H 'Content-Type: application/json' -d '"<idp-alias>"'

# Verify the link actually took - don't assume it from a 204 on the create call.
curl -s "$BASE/admin/realms/$REALM/organizations/<org-id>/identity-providers" -H "$H" \
  | jq -r '.[].alias'
```

**Creating an IdP does not associate it with any organization.** Without this call the domain
cannot be routed to it. On 26.8 the link alone routes nobody either: Stage 5 is what switches
routing on.

## Stage 5 — Route the domain to the IdP, with auto-redirect — the step that gets skipped

Since Keycloak 26.8 each organization domain carries its own routing: `identityProviderAlias`
(which linked IdP handles that domain) and `autoRedirect` (send the user there without showing a
form). There is no per-domain endpoint. Change the domain inside the organization representation
and `PUT` the whole organization back:

```bash
curl -s "$BASE/admin/realms/$REALM/organizations/<org-id>" -H "$H" \
  | jq --arg d "<customer-email-domain>" --arg a "<idp-alias>" \
      '(.domains[] | select(.name == $d)) += {identityProviderAlias: $a, autoRedirect: true}' \
  | curl -s -X PUT "$BASE/admin/realms/$REALM/organizations/<org-id>" -H "$H" \
      -H 'Content-Type: application/json' --data-binary @-

# Read it back.
curl -s "$BASE/admin/realms/$REALM/organizations/<org-id>" -H "$H" | jq '.domains'
```

You need both fields. With `identityProviderAlias` and no `autoRedirect`, the IdP only appears as a
button beside your password form. With `autoRedirect` and no `identityProviderAlias`, nothing
happens at all.

## Do you need a custom flow at all?

**No, on Keycloak 26.8+.** Once the domain is routed with auto-redirect, the realm's default
built-in `browser` flow sends a matching address straight to the IdP. A returning user who has
already federated is redirected the same way. You don't author or bind any flow. Confirm by
testing (below) before assuming you need more.

The custom flows below are for Phase Two deployments only. They use `ext-auth-home-idp-discovery`,
an authenticator from Phase Two's `keycloak-orgs` extension, which stock Keycloak does not ship.
If the default flow on such a deployment does *not* already discover by organization (a
customized default flow), or if you specifically want "with orgs-check" behavior (the user is
also treated as an organization member, not just redirected), author a custom flow from
[`assets/home-idp.partial-import.json`](assets/home-idp.partial-import.json) or
[`assets/home-idp-with-orgs-check.partial-import.json`](assets/home-idp-with-orgs-check.partial-import.json).
**Both assets set `forwardToLinkedIdp=true`** — the authenticator's factory default is `false`,
which silently prevents any redirect at all.

**Note on authoring**: Keycloak's `partialImport` endpoint does **not** handle authentication
flows — it has no handler for them, so an `authenticationFlows` array is silently ignored (HTTP
200, `added: 0`, no error). The admin console's "Partial import" action and `kcadm.sh create
partialImport` hit that same endpoint and fail the same way. Author flows with the explicit
sequence instead: `POST .../authentication/flows` to create the flow, `POST
.../authentication/flows/<flow>/executions/execution` per step, `PUT
.../authentication/flows/<flow>/executions` to set each requirement, and `POST
.../authentication/executions/<exec-id>/config` to attach authenticator config. Then bind via the
realm representation's `browserFlow` field (realm-wide) or the client's
`authenticationFlowBindingOverrides` (single client).

## Verify by logging in, not by reading configuration

Every setting here can be correct-looking and inert, and no endpoint reports routing — routing
is behaviour. Perform a real login twice:

| Submit on the login page | Expect |
|---|---|
| an address at the customer's domain | **no password field**; the browser is sent to the customer's IdP |
| an address at any other domain | **a password field**, and password login still completes |

The second row is not optional — it's what distinguishes correct domain discovery from a
redirector that hijacks every login.

[`scripts/browser_login.py`](scripts/browser_login.py) drives the whole round trip over plain
HTTP and prints where each step went:

```bash
python3 scripts/browser_login.py --realm acme --client acme-portal \
  --redirect-uri http://localhost:9999/callback \
  --username someone@customer.example --idp-username u --idp-password p
```

Two client-side details that otherwise cost an afternoon:

- Keycloak sets `AUTH_SESSION_ID` and `KC_RESTART` as `Secure; SameSite=None`. Browsers send
  them over `http://localhost` anyway (loopback is a secure context); most HTTP client libraries
  will not, and every form POST then returns `400` *"Cookie not found."* Clear the flag on each
  response (`cookie.secure = False` in Python `requests`).
- Test both a user who has **never** federated and one who **already** has a federated identity.
  On 26.8 with auto-redirect both get an immediate redirect. On 26.7 and older the first-time
  user was offered a link instead, and a check could pass on the first login and fail on the
  second.

Afterwards, a correctly federated user has a non-empty federated identity and **no** password
credential in your realm — hand-creating a local account with a matching email reproduces some
of the behavior while being the opposite of federation.

## Provider settings that bite

- **The redirect URI the customer must whitelist** is
  `{base}/realms/{realm}/broker/{alias}/endpoint` — it contains the alias, so choose the alias
  *before* asking them to whitelist anything.
- **`hideOnLogin`** — keeps the customer's button off the login page your own staff see. On 26.8
  with the domain routed and auto-redirect on, it does not affect the routed domain. Measured: a
  matching address still gets a 303 to the broker, and an internal user's password page loses
  the button. On 26.7 and older it removed the only route a first-time user had, so don't carry
  that advice forward.
- **`syncMode`** — `IMPORT` copies profile fields on first login only; `FORCE` refreshes them on
  every login, usually right when the customer's directory is authoritative.

## Not organization *restriction*

This is an automatic redirect, not a membership gate. A user whose email domain matches no
organization falls through to the password fallback. "Only members of this organization may log
in at all" is a different, related mechanism not covered here.

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| Matched domain shows the password form with an SSO button beside it | The domain is not routed: no `identityProviderAlias`, or `autoRedirect` is false (Stage 5) |
| `400` "Identity provider '…' is not associated with organization …" when routing the domain | The IdP is not linked to that organization yet (Stage 4 first) |
| `kc.org.domain` / `kc.org.broker.redirect.mode.email-matches` set on the IdP, then gone | Keycloak 26.8 moved routing to the domain and drops those keys. Use Stage 5 |
| Matched domain still shows the password form (custom-flow path, Phase Two only) | `forwardToLinkedIdp` left at its `false` default |
| Everyone gets forwarded to the provider | An identity-provider-redirector execution in the bound flow |
| `400` "Cookie not found" while scripting | `Secure` cookies not sent over http by the client |
| `invalid_redirect_uri` at the customer's provider | They whitelisted a different alias than the one created |
| `organizationsEnabled` doesn't stick | A realm PUT omitting fields resets them — re-fetch and re-PUT the full representation |
| `partialImport` returned 200 but no flow exists | That endpoint ignores authentication flows entirely — author them explicitly |
