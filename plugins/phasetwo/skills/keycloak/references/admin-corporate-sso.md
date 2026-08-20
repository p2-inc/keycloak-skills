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

> **⚠ Needs verification against the real extension.** The mechanism here is
> **[p2-inc `keycloak-orgs`](https://github.com/p2-inc/keycloak-orgs)** — a real, installable
> extension (Elastic License 2.0, same p2-inc pattern as `keycloak-magic-link`), not part of
> stock Keycloak, and **not** the same thing as Keycloak's own native, in-core Organizations
> feature (Phase Two deliberately does not enable that native feature — see the extension's own
> [note on this](https://github.com/p2-inc/keycloak-orgs/blob/main/docs/note-keycloak-organizations-feature.md)).
> The endpoints and payloads below were written against Keycloak's *native* organizations API
> before this distinction was caught, and have **not yet been corrected** against the real
> extension's actual REST surface (`/realms/{realm}/orgs`, not `/admin/realms/{realm}/organizations`
> — confirmed from the extension's own source). Confirm the extension is installed before relying
> on anything past this note, and treat the exact request/response shapes below as unverified
> until they're checked against a real deployment or the extension's source.

```bash
BASE=http://localhost:8080/auth       # include the relative path if one is configured
H="Authorization: Bearer $ADMIN_TOKEN"
REALM=<realm>
```

## The mechanism: organizations, not the flow editor

The `keycloak-orgs` extension has exactly one way to route by email domain, and it lives in the
**organizations** feature, not the authentication-flow editor where someone would look for it.
Three things must all be true, and each fails silently on its own:

| Missing | Symptom |
|---|---|
| The realm's organization support isn't switched on | No domain-based routing exists at all |
| An organization doesn't hold the customer's email domain, **verified** | Discovery has nothing to match (an unverified domain is stored happily and never matches) |
| The IdP is created but **not linked** to the organization | The provider works, but the login page just shows an SSO button to everybody — no routing |

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

## Stage 3 — Create the organization, with a verified domain

```bash
curl -s -X POST "$BASE/admin/realms/$REALM/organizations" -H "$H" \
  -H 'Content-Type: application/json' -d '{
    "name": "<org-name>",
    "alias": "<org-name>",
    "enabled": true,
    "description": "<Customer> - federated enterprise customer",
    "domains": [{"name": "<customer-email-domain>", "verified": true}]
  }'

# Get the org's id - the next step needs it.
curl -s "$BASE/admin/realms/$REALM/organizations" -H "$H" \
  | jq -r --arg n "<org-name>" '.[] | select(.name==$n) | .id'
```

**`verified: true` is not optional.** An unverified domain is accepted without complaint and
silently never matches during discovery — there is no error to tip you off.

## Stage 4 — Link the IdP to the organization — the step that gets skipped

```bash
# The body is a bare JSON STRING holding the provider alias, not an object.
curl -s -X POST "$BASE/admin/realms/$REALM/organizations/<org-id>/identity-providers" \
  -H "$H" -H 'Content-Type: application/json' -d '"<idp-alias>"'

# Verify the link actually took - don't assume it from a 204 on the create call.
curl -s "$BASE/admin/realms/$REALM/organizations/<org-id>/identity-providers" -H "$H" \
  | jq -r '.[].alias'
```

**Creating an IdP does not associate it with any organization.** Without this call, discovery
will never find the IdP for that domain no matter how correct everything else is — the provider
just sits there, visible as a generic SSO button to everyone, routing nobody.

## Do you need a custom flow at all?

On stock Keycloak, **often not**: once organizations are enabled and an IdP is linked to a
verified-domain organization, the realm's default built-in `browser` flow already performs Home
IdP Discovery — no flow authoring or binding required. Confirm this is the case on your version
by testing (Stage 5) before assuming you need more.

If the default flow on this deployment does *not* already discover by organization (older
versions, a customized default flow), or if you specifically want "with orgs-check" behavior
(the user is also treated as an organization member, not just redirected), author a custom flow
from [`../assets/home-idp.partial-import.json`](../assets/home-idp.partial-import.json) or
[`../assets/home-idp-with-orgs-check.partial-import.json`](../assets/home-idp-with-orgs-check.partial-import.json).
**Both assets set `forwardToLinkedIdp=true`** — the authenticator's factory default is `false`,
which silently prevents any redirect at all.

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

If binding separately (manual path, or an already-existing flow): set the realm representation's
`browserFlow` field (realm-wide) or the client's `authenticationFlowBindingOverrides` (single
client) — same mechanism as every other flow-binding intent in this router.

## Verify by logging in, not by reading configuration

Every setting here can be correct-looking and inert, and no endpoint reports routing — routing
is behaviour. Perform a real login twice:

| Submit on the login page | Expect |
|---|---|
| an address at the customer's verified domain | **no password field**; the browser is sent to the customer's IdP |
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
- **`hideOnLogin`** — tempting, to keep one customer's button off a shared login page. Measured:
  setting it true removes the route for the **matched** domain too, leaving those users with no
  password field *and* no way forward. Leave it visible unless you've verified the matched-domain
  path still works.
- **`syncMode`** — `IMPORT` copies profile fields on first login only; `FORCE` refreshes them on
  every login, usually right when the customer's directory is authoritative.

## Not organization *restriction*

This is an automatic redirect, not a membership gate. A user whose email domain matches no
organization falls through to the password fallback. "Only members of this organization may log
in at all" is a different, related mechanism not covered by this intent.

## Troubleshooting

| Symptom | Cause |
|---|---|
| Matched domain still shows the password form | `forwardToLinkedIdp` left at its `false` default (custom-flow path), or the IdP is not linked to the organization |
| SSO button shown to everyone, nothing routes | Provider created but not linked to an organization |
| Domain never matches | The organization's domain is not marked `verified` |
| Everyone gets forwarded to the provider | An identity-provider-redirector execution in the bound flow |
| Matched domain gets neither password nor route | `hideOnLogin` is true on the provider |
| `400` "Cookie not found" while scripting | `Secure` cookies not sent over http by the client |
| `invalid_redirect_uri` at the customer's provider | They whitelisted a different alias than the one created |
| `organizationsEnabled` doesn't stick | A realm PUT omitting fields resets them — re-fetch and re-PUT the full representation |
