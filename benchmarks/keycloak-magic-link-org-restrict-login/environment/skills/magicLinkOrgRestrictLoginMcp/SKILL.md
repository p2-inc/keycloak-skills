---
name: magicLinkOrgRestrictLoginMcp
description: >-
  Restrict passwordless magic-link login so only members of a specific organization ever
  receive the login link, on a Phase Two hosted Keycloak, using the Keycloak MCP server. Use
  this whenever someone wants "magic link login restricted to org X", "passwordless login
  gated by organization membership", "only email the login link to people on this team", or
  describes a user logging in via magic link where whether they get in depends on their
  organization membership (as signalled by account_hint). This is NOT plain magic-link with no
  restriction (a simpler, different flow), and NOT the org gate on a password login (a
  different flow with no magic-link step at all) — it is the combination of both, via a custom
  flow authored with importAuthenticationFlow that runs the membership check BEFORE the login
  email is sent. Covers the load-bearing execution order and the
  `account_hint`/`prompt=select_account` trigger requirement.
---

<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# Magic-link login restricted to one organization's members — via the Keycloak MCP server

## What this is, and what it isn't

Magic-link login (open an emailed link, you're in, no password) **combined with** a membership
gate: only someone who belongs to the organization named in the request's `account_hint` ever
receives the link. Neither half is new by itself — plain magic-link has no organization check,
and the password-login org gate (`Org Browser Flow` + `ext-select-org`) has no magic-link step
— so combining them needs a **custom flow**.

**What makes this different from just adding a step**: the membership check has to run
**before** any mail goes out. Reveal "an account exists here" only after confirming the
requester belongs to the hinted organization — never before. The flow below does this by
collecting just an identifier first (setting it in the auth-session context, no credential
check yet), running the org check against that, and only then reaching the magic-link step
itself.

## Tools this skill drives (Keycloak MCP server)

| Purpose | Tool |
|---|---|
| Identify caller / realm | `whoAmI` |
| Create the organization | `createOrganization` |
| Add a member | the org membership tool for this deployment (confirm the exact name with a tool listing) |
| Confirm no flow already does this | `listAuthenticationFlows` |
| Author the flow **and bind it**, in one call | `importAuthenticationFlow` (needs the atomic-flows extension — see below) |
| Inspect/adjust the `ext-select-org` step's matching mode | `listFlowExecutions` / `setExecutionAuthenticatorConfig` |
| Configure outgoing mail | `setSmtpSettings` |
| Bind an already-existing flow | `bindRealmAuthenticationFlow` / `bindClientAuthenticationFlow` |
| Confirm bindings | `getAuthenticationBindings` |

## Prerequisite: the keycloak-orgs extension

The real **[p2-inc `keycloak-orgs`](https://github.com/p2-inc/keycloak-orgs)** extension, not
Keycloak's native Organizations feature. If `listOrganizations` errors rather than returning an
empty list, it isn't installed — say so and stop.

## Stage 1 — Ask: match by organization NAME or ID?

`account_hint` can carry either, and `match_by_org_name` decides which is read. Ask what the
application actually sends — don't guess.

## Stage 2 — The organization and its member(s)

Create the organization, then add each intended member. Confirm membership actually stuck
rather than assuming a successful add call means it did.

## Stage 3 — Author the flow (and bind it)

Confirm with `listAuthenticationFlows` that no flow already does this. Authoring is not covered
by any tool other than `importAuthenticationFlow` — it returns a clear 404 if the
keycloak-atomic-auth-flows extension isn't installed; offer it rather than switching to REST
unsolicited.

```json
{
  "authenticationFlows": [ /* from assets/select-organization-magic-link.partial-import.json */ ],
  "authenticatorConfig": [ /* same asset */ ],
  "browserFlowBinding": "Select organization magic link"
}
```

**The ordering inside the asset's forms sub-flow is load-bearing, not cosmetic** — verify it
matches this table if authoring by hand instead of using the asset:

| Execution | Requirement | Config | Why this position |
|---|---|---|---|
| `ext-auth-username-auth-note` | REQUIRED | `setUserInContext=true` | Collects an identifier and sets it in context — **before** any membership or credential check. `ext-select-org` needs a user to check. |
| `ext-select-org` | REQUIRED | `match_by_org_name=<true\|false>` | **The gate.** A non-member fails here; `ext-magic-form` is never reached — no mail goes out to them. |
| `ext-magic-form` | REQUIRED | `ext-magic-create-nonexistent-user=false` | Only reached once membership passed. `false` here for the same reason plain magic-link sets it — the factory default (`true`) would provision an account for anyone reaching this point. |

Putting `ext-magic-form` before `ext-select-org` would send mail regardless of membership and
defeat the entire point of gating — this is the one thing not to improvise around. Read the
real, hash-prefixed alias back from `importAuthenticationFlow`'s response rather than assuming
the asset's name.

## Stage 4 — Realm mail settings

`setSmtpSettings` — same silent-failure trap as plain magic-link. Verify by checking what
actually left (a capture point in test contexts), not by trusting a success response.

## Stage 5 — The account_hint trap, again

`ext-select-org` only runs when the request carries `account_hint` or `prompt=select_account` —
confirm the application actually sends one of those two parameters on every login that should
be gated.

## Stage 6 — Verify by logging in, not by reading configuration

1. A member with the correct `account_hint`: should receive mail with an action-token link;
   completing it returns an authorization code.
2. A non-member with the same `account_hint`: should receive **no mail at all** — check outgoing
   mail directly, since the identifier-collection step's page response may look identical
   either way.
3. An `account_hint` matching no real organization, for a genuine member of some other
   organization: also rejected — this is what proves membership is actually checked.

## Common errors

- **Everyone gets mail regardless of membership** — executions are out of order, or the bound
  flow is missing `ext-select-org` entirely.
- **Nobody gets mail, even members** — `setUserInContext` missing/false, or realm SMTP
  unconfigured.
- **`account_hint` set to a name but `match_by_org_name` is `"false"` (or vice versa)** — check
  both explicitly rather than assuming agreement.
- **A required MCP tool is missing** — report it and stop; do not switch to REST unsolicited.
