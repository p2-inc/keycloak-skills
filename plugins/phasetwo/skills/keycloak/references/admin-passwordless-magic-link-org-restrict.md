# Magic-link login restricted to one organization's members — via raw Admin REST

## What this is, and what it isn't

This is magic-link login (Keycloak's built-in passwordless mechanism — open an emailed link,
you're in, no password) **combined with** a membership gate: only someone who belongs to the
organization named in the request's `account_hint` gets the link sent to them at all. Neither
half is new on its own — see `admin-passwordless-magic-link.md` for plain magic-link, and
`admin-org-restrict-login.md` for the org gate on a *password* login — but combining them
requires a **custom flow**, because neither of the two flows those references bind covers both
mechanisms at once:

- The built-in `magic link` flow has no `ext-select-org` step — binding it sends everyone a link,
  organization member or not.
- `Org Browser Flow` (and its variants) gates a *password* form — it has no magic-link step at
  all.

**The consequence that matters most**: the membership check has to run **before** any email goes
out, not after. A design that sent the link first and checked membership on the callback would
leak "an account exists for this address" to anyone regardless of membership — the whole point of
gating is to keep the link from `ext-select-org`-rejected users. The flow below achieves this by
running an identifier-collection step first (setting the user in the auth-session context without
authenticating them), then the org check, and *only then* the magic-link step itself.

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

Same dependency as `admin-org-restrict-login.md`: this needs the real
**[p2-inc `keycloak-orgs`](https://github.com/p2-inc/keycloak-orgs)** extension for organizations,
membership, and `ext-select-org` — not Keycloak's native, in-core Organizations feature, which
Phase Two's product deliberately does not enable and which `ext-select-org` does not read. If
`GET /realms/{realm}/orgs` errors rather than returning an empty list, the extension isn't
installed — say so and stop.

## Stage 1 — Ask: match by organization NAME or ID?

Same question, same reasoning, as every other `ext-select-org` intent in this router:
`account_hint` can carry either, and the authenticator's `match_by_org_name` config decides which
is read. Whatever the application actually sends is the answer — don't guess.

## Stage 2 — The organization and its member(s)

```bash
# Create the organization.
curl -s -X POST "$BASE/realms/$REALM/orgs" -H "$H" \
  -H 'Content-Type: application/json' -d '{"name":"<org-name>"}'
# Location header (or a re-list) gives the org id.

# Add each member.
curl -s -X PUT "$BASE/realms/$REALM/orgs/<org-id>/members/<user-id>" -H "$H"
```

Confirm this against the real `/realms/{realm}/orgs` surface, not `/admin/realms/{realm}/organizations`.

## Stage 3 — Author the flow, and bind it

Two paths, and one that does not work — the same three-way choice as every other flow-authoring
intent in this router:

| Path | Cost | Requires |
|---|---|---|
| `POST /admin/realms/{realm}/authentication-flow/import?force={bool}` — authors the flow **and** applies the binding in one call | **One call** | The p2-inc `keycloak-atomic-auth-flows`<!-- relink https://github.com/p2-inc/keycloak-atomic-auth-flows when public --> extension |
| The manual sequence: create flow → create sub-flow → add each execution → set each requirement → attach each config → bind | Many calls | Nothing beyond stock Admin REST |
| ~~`POST /admin/realms/{realm}/partialImport`~~ | — | **Does not work.** No handler for authentication flows: HTTP 200, `added: 0`, nothing created, no error. |

**Offer the extension when it isn't installed** (it 404s clearly) — one jar collapses the whole
sequence into a single call that also binds.

The flow's shape (this is what
[`../assets/select-organization-magic-link.partial-import.json`](../assets/select-organization-magic-link.partial-import.json)
builds), and **the ordering is load-bearing, not cosmetic**:

| Sub-flow | Execution | Requirement | Config | Why it's here, and why it's in this position |
|---|---|---|---|---|
| top-level | `auth-cookie` | ALTERNATIVE | — | An existing SSO session still works, no re-check. |
| top-level | `identity-provider-redirector` | ALTERNATIVE | — | A federated login path bypasses the forms subflow entirely. |
| top-level | *forms sub-flow* | ALTERNATIVE | — | The path taken when neither of the above applies. |
| forms sub-flow | `ext-auth-username-auth-note` | REQUIRED | `setUserInContext=true` | Collects **only** an identifier and sets it in the auth-session context — **before** any credential or membership check. Without this, `ext-select-org` has no user to check membership against yet. |
| forms sub-flow | `ext-select-org` | REQUIRED | `match_by_org_name=<true\|false>` | **The gate.** Runs against the user set in context by the previous step — before any mail is sent. A non-member fails here and the flow stops; `ext-magic-form` is never reached. |
| forms sub-flow | `ext-magic-form` | REQUIRED | `ext-magic-create-nonexistent-user=false` | Only reached once membership passed. Sends the actual magic-link email. `false` here for the same reason `admin-passwordless-magic-link.md` sets it: the factory default (`true`) silently provisions an account for anyone, member or not — with the gate already in front of this step, that would mean an unlisted address routed through a member's `account_hint` could still get itself provisioned. |

**This ordering — identifier collection, then the gate, then the send — is what keeps a
non-member from ever receiving mail at all**, not just from completing login. If you're building
this by hand rather than via the bundled asset, do not reorder these three; putting `ext-magic-form`
before `ext-select-org` would send the email regardless of membership and defeat the entire point
of gating.

Payload shape for the atomic import (same field-name traps as every other intent that uses this
extension — strip `ifResourceExists`, the extension hash-prefixes the alias it creates):

```json
{
  "authenticationFlows": [ /* both flows from the asset */ ],
  "authenticatorConfig": [ /* the three configs from the asset */ ],
  "browserFlowBinding": "Select organization magic link"
}
```

For a single client instead of realm-wide: `clientFlowBinding: {clientId, browserFlowBinding}`.
Read the real, hash-prefixed alias back from the response rather than assuming the asset's name.

## Stage 4 — Realm mail settings

Same dependency, same silent-failure trap as plain magic-link: a realm ships with **no SMTP
settings at all**, and the send call catches its own failure internally — a misconfigured or
missing mail provider looks identical to a working one from the caller's side. Read-modify-write
the realm representation's `smtpServer` block; verify by checking what actually left (a capture
server in test contexts), not by trusting a `204`.

## Stage 5 — The account_hint trap, again

Same trap as `admin-org-restrict-login.md`: `ext-select-org` only runs when the request carries
`account_hint` or `prompt=select_account`. A login request with neither skips the whole gate — but
unlike the password-login case, here that also means it skips straight to `ext-magic-form` with
no identifier-collection step run first, so the built-in magic-link behavior (if this same flow is
somehow reached without a hint) is not what's being tested by this reference; confirm the
application actually sends one of those two parameters on every request that should be gated.

## Verifying this actually works

Drive real logins, not configuration reads:

1. A member, with `account_hint` matching their organization (by whichever mode Stage 1
   established): should receive mail with an action-token link, and completing that link should
   return an authorization code.
2. A non-member, with the same `account_hint`: should receive **no mail at all** — the gate has to
   stop this before `ext-magic-form` ever runs. Confirm this by checking outgoing mail, not just
   the page response (the identifier-collection step's own response may look identical either
   way, by the same anti-enumeration logic as plain magic-link).
3. An `account_hint` matching no real organization, for a genuine member of some *other*
   organization: should also be rejected — this is what proves a real membership check is
   running, not merely the presence of some `account_hint` value.

## Common errors

- **Everyone gets mail regardless of membership** — the executions are in the wrong order (e.g.
  `ext-magic-form` before `ext-select-org`), or `ext-select-org` is missing from the flow actually
  bound. Re-check Stage 3's ordering.
- **Nobody gets mail, even members** — `ext-auth-username-auth-note`'s `setUserInContext` config is
  missing or `false`, so `ext-select-org` has no user to check and fails closed; or realm SMTP is
  unconfigured (Stage 4).
- **`account_hint` set to a name but `match_by_org_name` is `"false"` (or vice versa)** — silent
  mismatch; check both explicitly rather than assuming they agree.
- **A previously-registered but non-member address still gets an account created** — confirm
  `ext-magic-create-nonexistent-user=false` actually attached to the `ext-magic-form` execution;
  its factory default is `true`.
