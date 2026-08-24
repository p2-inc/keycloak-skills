# Execution order in authentication flows — creating and modifying

Shared by every intent in this router that authors or edits a flow. Read it alongside the intent's
own reference file: that file states **which** order is correct for its flow, this one states **how
to actually get that order onto the server and prove it stuck**.

## Why this file exists

Order is not cosmetic — in these flows it *is* the configuration:

| Flow | If the order is wrong |
|---|---|
| magic-link restricted to an org | the send step runs before the org gate, so **non-members receive the login email** |
| email-OTP passwordless | a stock identifier step ahead of `ext-email-otp` **leaks which addresses have accounts** |
| password + email-OTP MFA | the code step runs without the password gating it, so **a wrong password still sends mail** |
| 0-password (passkey **or** magic link) | `ext-magic-form` above the WebAuthn step means **a user with no passkey lands on a ceremony they cannot complete** |
| homeIdp / corporate SSO | `identity-provider-redirector` ahead of `auth-cookie` means a request carrying `kc_idp_hint` **bypasses an existing SSO session** and re-authenticates at the IdP |

Every one of those failures is silent. Nothing errors, the admin console renders the flow, and the
damage only shows up as wrong behaviour at login — which is why order has to be *verified*, never
assumed.

## The rule

**The create calls do not establish order. Read the order back and repair it before calling the
flow done.**

This holds on all three authoring paths and on every Keycloak version. Treat "I passed `priority`"
as a request, not a result.

## Path 1 — `importAuthenticationFlow` (one shot, correct by construction)

The [keycloak-atomic-auth-flows](https://github.com/p2-inc/keycloak-atomic-auth-flows) extension's
import endpoint carries the asset's own `priority` values, so ordering comes out right for free.
When the intent ships a `../assets/*.partial-import.json`, this is the path that avoids the whole
problem. Still read the flow back once — the alias is hash-prefixed, so you need the real name
anyway.

Returns a clear 404 when the extension isn't installed. Offer installing it, then fall back to
Path 2.

**Not** Keycloak's own `partialImport` endpoint (or the console's "Partial import"): it has no
handler for authentication flows and silently ignores them — HTTP 200, nothing created.

## Path 2 — MCP component path (the default)

`addFlow` → `addSubFlow` → `addAuthenticator` per leaf → `setExecutionRequirement` → bind.

Pass `priority` explicitly on **every** `addSubFlow` and `addAuthenticator` call. Both **append**
when it is omitted, landing at `(last sibling's priority + 1)`, so the result is just call order —
and creating the forms sub-flow before `auth-cookie` exists puts the sub-flow first.

Then **verify and repair**:

```
listFlowExecutions(flowAlias="<flow>")        # returns index, level, priority, requirement, provider
```

Compare against the intent's order table. If it doesn't match, repair with
`raiseExecutionPriority` / `lowerExecutionPriority` — each call swaps one execution with one
adjacent sibling, so moving a step up two positions is two calls. Re-read after each repair.

Reorder **one level at a time**: a flow and its sub-flow are separate sibling sets. Fix the
top-level order, then fix the order inside each sub-flow.

## Path 3 — raw Admin REST

`POST .../authentication/flows/{alias}/executions/flow` and `.../executions/execution`, both with
`priority` in the body. Same append behaviour, same repair tool:

```bash
# read back
curl -s "$BASE/admin/realms/$REALM/authentication/flows/$(jq -rn --arg f "$FLOW" '$f|@uri')/executions" -H "$H" \
  | jq -r '.[] | "\(.index) lvl=\(.level) pri=\(.priority) \(.requirement) \(.providerId // .displayName)"'

# repair, one adjacent swap per call
curl -s -X POST "$BASE/admin/realms/$REALM/authentication/executions/$EXEC_ID/raise-priority" -H "$H"
```

## What "pass priority explicitly" does *not* buy you

`priority` in the request body is honoured only from **Keycloak 25** onward (added 2024-05-29); on
24 and older it is ignored and every call appends regardless.

**But passing it is necessary, not sufficient, even on 25+ — and top-level executions are where it
breaks.** Recorded from three consecutive live attempts at building a `homeIdp` flow through the
MCP component path:

| Attempt | Priority scheme | Top-level result | Nested sub-flow result |
|---|---|---|---|
| 1, 2 | spaced (`10`, `20`, `30`, …) | shuffled | — |
| 3 | small sequential (`1`, `2`, `3`, …), matching the org-broker asset's style | **still shuffled** | **exactly as requested** |

Changing the numbering scheme did not fix it. The nested sub-flow came out right in the same run
that the top level came out wrong, so this is not "the agent passed bad numbers" — the top-level
sibling set is simply not reliably ordered by the priority the create call asked for.

Two consequences for how you work:

1. **Never report a flow as built off the back of the create calls' return values.** Several of them
   echo the position you asked for, which is a request being repeated back, not a server state.
2. **Budget for the repair step.** Verify-then-repair is part of authoring a flow, not an error
   path — assume the top level will need it.

Where the MCP server exposes it, an `orderWarning` field on `addAuthenticator` / `addSubFlow`
responses flags the case where the server did not honour the requested priority; and a
`reorderFlowExecutions` tool, where present, does the raise-priority repair for a whole level and
fails loudly if the final order still isn't the one asked for. Neither is guaranteed to be on the
server you're talking to — check, and fall back to the read-back-and-repair loop above, which works
everywhere.

## Before calling it done

- [ ] `listFlowExecutions` output matches the intent's order table, at **every** level.
- [ ] Requirements are right too (`ALTERNATIVE` vs `REQUIRED` vs `DISABLED`) — order and requirement
      are independent, and a correct order with the wrong requirement fails just as silently.
- [ ] The flow is bound to the surface the intent names (realm `browser`, a client override, or the
      IdP's post-broker/first-broker login flow — these are different surfaces).
- [ ] Behaviour verified by an actual login, not by reading configuration back. Order bugs are
      invisible in config and obvious at the login screen.
