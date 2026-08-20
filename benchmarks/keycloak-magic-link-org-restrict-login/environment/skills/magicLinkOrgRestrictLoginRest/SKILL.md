---
name: magicLinkOrgRestrictLoginRest
description: >-
  Restrict passwordless magic-link login so only members of a specific organization ever
  receive the login link, on a self-managed Keycloak running the p2-inc keycloak-orgs and
  keycloak-magic-link extensions, using the Admin REST API only (no MCP server involved). Use
  this whenever someone wants "magic link login restricted to org X", "passwordless login
  gated by organization membership", "only email the login link to people on this team", or
  describes a user logging in via magic link where whether they get in depends on their
  organization membership (as signalled by account_hint). This is NOT plain magic-link with no
  restriction (a simpler, different flow), and NOT the org gate on a password login (a
  different flow with no magic-link step at all) — it is the combination of both, via a custom
  flow that runs the membership check BEFORE the login email is sent. Covers authoring that
  flow (including why Keycloak's own partialImport endpoint cannot do this), the load-bearing
  execution order, and the `account_hint`/`prompt=select_account` trigger requirement.
---

# Magic-link login restricted to one organization's members — via raw Admin REST

## What this is, and what it isn't

This is magic-link login (open an emailed link, you're in, no password) **combined with** a
membership gate: only someone who belongs to the organization named in the request's
`account_hint` gets the link sent to them at all. Neither half is new on its own:

- Plain magic-link binds Keycloak's built-in `magic link` flow — no organization check.
- The password-login org gate (`Org Browser Flow` + `ext-select-org`) has no magic-link step.

Combining them needs a **custom flow**, because neither of those two flows covers both
mechanisms at once.

**The consequence that matters most**: the membership check has to run **before** any email
goes out, not after. A design that sent the link first and checked membership on the callback
would leak "an account exists for this address" to anyone regardless of membership. The flow
below achieves this by running an identifier-collection step first (setting the user in the
auth-session context without authenticating them), then the org check, and *only then* the
magic-link step itself.

```bash
BASE=http://localhost:8080/auth       # include the relative path if one is configured
H="Authorization: Bearer $ADMIN_TOKEN"
REALM=<realm>
```

## Prerequisite: the keycloak-orgs extension

Organizations, membership, and `ext-select-org` come from the real
**[p2-inc `keycloak-orgs`](https://github.com/p2-inc/keycloak-orgs)** extension — not
Keycloak's native, in-core Organizations feature, which Phase Two's product deliberately does
not enable and which `ext-select-org` does not read. If `GET /realms/{realm}/orgs` errors
rather than returning an empty list, the extension isn't installed — say so and stop.

## Stage 1 — Ask: match by organization NAME or ID?

`account_hint` can carry either an organization's name or its ID, and `ext-select-org`'s
`match_by_org_name` config decides which is read. Ask what the application actually sends —
don't guess.

## Stage 2 — The organization and its member(s)

```bash
curl -s -X POST "$BASE/realms/$REALM/orgs" -H "$H" \
  -H 'Content-Type: application/json' -d '{"name":"<org-name>"}'
# Location header (or a re-list) gives the org id.

curl -s -X PUT "$BASE/realms/$REALM/orgs/<org-id>/members/<user-id>" -H "$H"
```

Confirm membership actually stuck (`GET .../orgs/<org-id>/members/<user-id>` → 204) rather than
assuming a successful PUT means it did.

## Stage 3 — Author the flow, and bind it

Two paths, and one that does not work:

| Path | Cost | Requires |
|---|---|---|
| `POST /admin/realms/{realm}/authentication-flow/import?force={bool}` — authors the flow **and** binds it in one call | **One call** | The [p2-inc keycloak-atomic-auth-flows](https://github.com/p2-inc/keycloak-atomic-auth-flows) extension |
| The manual sequence: create flow → create sub-flow → add each execution → set each requirement → attach each config → bind | Many calls | Nothing beyond stock Admin REST |
| ~~`POST /admin/realms/{realm}/partialImport`~~ | — | **Does not work.** No handler for authentication flows: HTTP 200, `added: 0`, nothing created, no error. |

**Offer the extension when it isn't installed** (it 404s clearly) — one jar collapses the whole
sequence into a single call that also binds.

The flow's shape (built by
[`assets/select-organization-magic-link.partial-import.json`](assets/select-organization-magic-link.partial-import.json)),
and **the ordering is load-bearing, not cosmetic**:

| Sub-flow | Execution | Requirement | Config | Why it's here, and why it's in this position |
|---|---|---|---|---|
| top-level | `auth-cookie` | ALTERNATIVE | — | An existing SSO session still works, no re-check. |
| top-level | `identity-provider-redirector` | ALTERNATIVE | — | A federated login path bypasses the forms subflow entirely. |
| top-level | *forms sub-flow* | ALTERNATIVE | — | The path taken when neither of the above applies. |
| forms sub-flow | `ext-auth-username-auth-note` | REQUIRED | `setUserInContext=true` | Collects **only** an identifier and sets it in the auth-session context — **before** any credential or membership check. Without this, `ext-select-org` has no user to check membership against. |
| forms sub-flow | `ext-select-org` | REQUIRED | `match_by_org_name=<true\|false>` | **The gate.** Runs against the user set in context by the previous step — before any mail is sent. A non-member fails here and the flow stops; `ext-magic-form` is never reached. |
| forms sub-flow | `ext-magic-form` | REQUIRED | `ext-magic-create-nonexistent-user=false` | Only reached once membership passed. Sends the actual magic-link email. `false` here for the same reason plain magic-link sets it: the factory default (`true`) silently provisions an account for anyone — with the gate already in front of this step, that would mean an unlisted address routed through a member's `account_hint` could still get itself provisioned. |

**This ordering — identifier collection, then the gate, then the send — is what keeps a
non-member from ever receiving mail at all.** If authoring by hand instead of using the bundled
asset, do not reorder these three; putting `ext-magic-form` before `ext-select-org` would send
the email regardless of membership and defeat the entire point of gating.

Payload shape for the atomic import:

```json
{
  "authenticationFlows": [ /* both flows from the asset */ ],
  "authenticatorConfig": [ /* the three configs from the asset */ ],
  "browserFlowBinding": "Select organization magic link"
}
```

Strip `ifResourceExists` from the asset before sending — it's a `partialImport` field the
atomic-flows payload rejects. Read the real, hash-prefixed alias back from the response rather
than assuming the asset's name.

## Stage 4 — Realm mail settings

Same silent-failure trap as plain magic-link: a realm ships with **no SMTP settings at all**,
and the send call catches its own failure internally. Read-modify-write the realm
representation's `smtpServer` block; verify by checking what actually left, not by trusting a
`204`.

## Stage 5 — The account_hint trap, again

`ext-select-org` only runs when the request carries `account_hint` or `prompt=select_account`.
A login request with neither skips the whole gate — and on this flow specifically, also skips
the identifier-collection step entirely. Confirm the application actually sends one of those two
parameters on every request that should be gated.

## Verifying this actually works

1. A member, with `account_hint` matching their organization: should receive mail with an
   action-token link, and completing that link should return an authorization code.
2. A non-member, with the same `account_hint`: should receive **no mail at all** — confirm this
   by checking outgoing mail directly, not just the page response (which may look identical
   either way, by the same anti-enumeration logic as plain magic-link).
3. An `account_hint` matching no real organization, for a genuine member of some *other*
   organization: should also be rejected — this is what proves a real membership check is
   running, not merely the presence of some `account_hint` value.

## Common errors

- **Everyone gets mail regardless of membership** — the executions are in the wrong order, or
  `ext-select-org` is missing from the flow actually bound. Re-check Stage 3's ordering.
- **Nobody gets mail, even members** — `ext-auth-username-auth-note`'s `setUserInContext` config
  is missing or `false`, so `ext-select-org` has no user to check and fails closed; or realm SMTP
  is unconfigured (Stage 4).
- **`account_hint` set to a name but `match_by_org_name` is `"false"` (or vice versa)** — silent
  mismatch; check both explicitly.
- **A non-member address still gets an account created** — confirm
  `ext-magic-create-nonexistent-user=false` actually attached to the `ext-magic-form` execution.
