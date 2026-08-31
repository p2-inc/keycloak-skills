# Building authentication flows — shape and execution order

Shared by every intent in this router that authors or edits a flow. Read it alongside the intent's
own reference file: that file states **what** its flow must contain and in which order, this one
states **how to shape it so the engine actually runs those steps**, and **how to get the order onto
the server and prove it stuck**.

Two independent ways a flow goes wrong, both silent: it is the wrong **shape** (steps land in a
sibling set where the engine discards them) or the right shape in the wrong **order**. Shape first —
an ordering fix on a mis-shaped level is wasted work.

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

## Shape — which level an execution belongs to

Order decides *when* a step runs among its siblings. Shape decides *which sibling set it is in at
all*, and that is the more dangerous of the two: get it wrong and the engine discards whole steps
without an error.

### The one invariant: every level is bucket-pure

`DefaultAuthenticationFlow` evaluates requirements **only among the direct children of one flow** —
there is no cross-level comparison in the execution algorithm. At each level it sorts children into
two buckets:

| Requirement | Bucket |
|---|---|
| `REQUIRED` | required |
| `CONDITIONAL` | **required** — same bucket as REQUIRED, despite the name |
| `ALTERNATIVE` | alternative |
| `DISABLED` | neither — a free rider, safe at any level |
| a step whose authenticator implements `ConditionalAuthenticator` | neither — it gates its own enclosing sub-flow instead |

Then, before anything runs:

```java
if (!requiredList.isEmpty() && !alternativeList.isEmpty()) {
    logger.warnf("REQUIRED and ALTERNATIVE elements at same level! ...");
    alternativeList.clear();          // the alternatives are erased
}
```

**Mixing the two buckets at one level deletes every ALTERNATIVE there.** Not deprioritized, not
run-after — erased, and the alternative bucket is only consulted at all when the required bucket is
empty. The single signal is a server-log `WARN` (which reports `null` for a purged sub-flow), so
the admin console, the Admin REST API and every MCP tool show a flow that looks exactly right.

**So: a level is either all-ALTERNATIVE, or all-REQUIRED/CONDITIONAL. A sub-flow is how you open a
new level when you need the other bucket.** That is the whole rule; everything below follows from it.

### The layering that falls out

```
<top-level flow>                          ← all-ALTERNATIVE level
├── auth-cookie                            ALTERNATIVE
├── auth-spnego                            DISABLED        (free rider)
├── identity-provider-redirector           ALTERNATIVE
└── <forms sub-flow>                       ALTERNATIVE     ← opens a level
    ├── <primary login step>               REQUIRED        ← all-REQUIRED level
    └── second factor:
        ├─ ONE method    → the method      REQUIRED        (flat sibling, no wrapper)
        └─ SEVERAL       → <2nd-factor sub-flow>  REQUIRED ← opens a level
                           ├── method A     ALTERNATIVE    ← all-ALTERNATIVE level
                           └── method B     ALTERNATIVE
```

Three corrections to the way this rule is usually stated in shorthand — each one contradicted by an
asset this repo ships and has verified:

- **"The primary login should be a sub-flow"** — the *container* is a sub-flow; the primary
  authenticator itself is a **leaf** in all nine shipped assets (`auth-username-password-form`,
  `ext-magic-form`, `ext-auth-home-idp-discovery`, `webauthn-authenticator-passwordless`, …). What
  needs to be a sub-flow is the thing that opens an all-REQUIRED level below an all-ALTERNATIVE one.
- **"Wrap the second factor in a REQUIRED sub-flow"** — only when there is **more than one** method
  to choose between. With a single second factor there is nothing to alternate, and it is a flat
  REQUIRED sibling: `username-password-email-otp-flow.partial-import.json` ships exactly that
  (`auth-username-password-form` REQUIRED → `ext-email-otp` REQUIRED, same level).
- **"…and that sub-flow is REQUIRED"** — its requirement is whichever bucket *its own level* uses,
  not always REQUIRED. In `zero-password-login.partial-import.json` the sub-flow holding the two
  ALTERNATIVE methods is itself **ALTERNATIVE**, because it sits at the top level beside
  `auth-cookie`. Making it REQUIRED there would purge `auth-cookie` and kill SSO resume.

### Alternatives must be siblings to alternate

Two `ALTERNATIVE` steps in *different* parent flows are not alternatives to each other as far as the
execution algorithm is concerned — each is evaluated only against its own siblings. To offer "A or
B", A and B must be children of the same flow.

(Separate mechanism, easy to confuse: Keycloak's **"Try another way"** credential-selection page is
built by `AuthenticationSelectionResolver`, which *does* walk up and across sub-flows. What the user
can pick from and what the engine buckets are two different lists.)

### CONDITIONAL

- **Only meaningful on a sub-flow execution.** On a leaf it is not "conditional" at all — it lands
  in the required bucket and runs unconditionally, and it breaks the `SETUP_REQUIRED` path that a
  genuine `REQUIRED` leaf gets, so an unconfigured credential throws instead of prompting setup.
- **It must contain an enabled condition step, or the entire sub-flow is skipped on every login** —
  silently. `conditionalAuthenticatorList.isEmpty()` counts as "condition not met".
- **Conditions are identified by type, not by name.** The engine tests
  `instanceof ConditionalAuthenticator`; the `conditional-*` prefix is a stock naming convention.
  Phase Two ships `ext-auth-condition-known-user`, which gates identically despite the name.
- **All conditions in the sub-flow are AND-ed**, and only `DISABLED` takes a condition out of play.
- **Position is irrelevant to the engine, but put the condition first anyway.**
  `isConditionalSubflowDisabled` scans the sub-flow's whole child list and evaluates every condition
  *before* any child runs, so a condition sitting last gates exactly as well as one sitting first.
  Put it first regardless: a gate rendered below the steps it gates reads as dead config to anyone
  reviewing the flow, and stock Keycloak puts its own `conditional-user-configured` first
  (priority 10 in `Browser - Conditional 2FA`). `addConditional` positions it for you.
- **`conditional-user-configured` evaluates its SIBLING steps, and that is easy to misread as
  per-user gating when it isn't.** It asks whether the user has those siblings' credentials
  configured — `anyMatch` when the siblings are ALTERNATIVE, `allMatch` when REQUIRED. So a single
  sibling whose `configuredFor` is unconditionally `true` makes the gate always match and the
  sub-flow run for **every** user. `ext-email-otp` is exactly such a step (it needs no stored
  credential: `configuredFor` returns `true`), so a "second factor only if the user has one"
  sub-flow that offers email OTP as one of its alternatives is not conditional at all in practice —
  everyone gets the branch. That may be what you want (email OTP as a universal fallback); just
  don't describe it as conditional.
- **It occupies the required bucket**, so a CONDITIONAL sub-flow purges ALTERNATIVE siblings exactly
  as a REQUIRED one would.

### A gate belongs in every branch that can complete a login

An authorization gate (`ext-select-org`) placed only in the forms sub-flow is bypassed by any
top-level ALTERNATIVE that can finish the login on its own — a live SSO cookie, or a
`kc_idp_hint` redirect. Both `org-browser-flow-by-org-*` and `home-idp-with-orgs-check` therefore
wrap **each** branch (`Cookies Sub-Flow`, `IDP Sub-Flow`, `Forms Sub-Flow`), repeating the gate in
every one. Gate placement within a branch is an *ordering* question — see the order rules below;
in `select-organization-magic-link` the gate sits in the middle, before the send step, so a
non-member never receives mail.

### If the ask is X, the shape is Y

| The ask | Shape |
|---|---|
| One primary login, nothing after it | Primary as a REQUIRED leaf in an ALTERNATIVE `forms` sub-flow |
| Two primary logins, user picks (passkey **or** magic link) | Both ALTERNATIVE, **same** sub-flow |
| Primary, then one mandatory second factor | Both REQUIRED leaves, same sub-flow |
| Primary, then a **choice** of second factors | Second factors ALTERNATIVE inside a sub-flow whose own requirement matches its level |
| A step only when some condition holds | CONDITIONAL sub-flow + a `ConditionalAuthenticator` child + the gated steps |
| Restrict who may complete login at all | The gate in **every** branch that can complete a login |

Building this with MCP tools: `addFlow` → `addSubFlow` / `addAuthenticator` (pass `requirement`
**and** `priority` on every call — a step added without `requirement` is created `DISABLED` and does
nothing) → `addConditional` builds the CONDITIONAL-sub-flow-plus-condition shape in one call →
`reorderFlowExecutions` per level.

### Checking shape from `listFlowExecutions` alone

The purge is invariant-checkable without a login: group the output by `level` **within each parent**,
and assert no group contains both an `ALTERNATIVE` and a `REQUIRED`/`CONDITIONAL` entry. Any group
that does has already lost its alternatives.

## Give every execution a distinct priority — ties are unorderable

`ExecutionComparator` is a bare `o1.priority - o2.priority` with **no tie-break**. Two siblings
holding the same priority therefore have *no defined order* — whatever the query returns that day.

Worse, they cannot be fixed afterwards. `raise-priority` swaps the two executions' priority
**values** with the preceding sibling; swapping equal values writes the same numbers back. HTTP 204,
nothing moved. Every repair call succeeds and the order never changes, which reads exactly like an
API or Keycloak-version bug and is neither.

**This starts at flow creation, not at repair.** A flow is born tied if the payload that created it
had ties — and both paths inherit them:

- **Atomic import / any `*.partial-import.json`** — the `priority` values in the asset are written
  through verbatim.
- **The manual REST sequence** — replaying an asset step by step and passing its `priority` values
  reproduces the ties exactly.

Keycloak's own built-in **`post org broker login`** flow ships three executions at priority 0, so a
copy of it made in the admin console starts unorderable. That is the one case here you cannot fix
by authoring: copy it, then assign distinct priorities before doing anything else.

### How a flow ends up tied without anyone asking for it

The add calls space priorities correctly on their own (`getNextPriority` = last sibling + 1). The
usual way a flow collapses to all-zeros is the **requirement-setting call afterwards**:

```bash
# WRONG - resets this execution's priority to 0
curl -X PUT .../executions -d '{"id":"<id>","requirement":"ALTERNATIVE"}'

# RIGHT - send the priority back with it
curl -X PUT .../executions -d '{"id":"<id>","requirement":"ALTERNATIVE","priority":10}'
```

`PUT .../executions` takes a whole `AuthenticationExecutionInfoRepresentation`, and `priority` is a
primitive `int` on it — a body that omits the field deserializes it as **0**, and the server applies
it. Set requirements on four steps that way and all four end up at priority 0: tied, unordered, and
now unfixable by `raise-priority`. That is usually what has happened when reorder calls "return 204
and do nothing".

Observed live: a hand-built password+2FA flow came out with all seven executions at priority 0 for
exactly this reason.

So, when authoring: **distinct, increasing priorities on every sibling** — space them (0, 10, 20 …)
so a later insertion doesn't force a renumber. Every asset in `../assets/` now does this; two of
them (`post-org-broker-login-select-organization`, `select-organization-magic-link`) shipped ties
until it was caught this way.

And when repairing a flow that is *already* tied: **assign the priorities outright** rather than
swapping toward them — `PUT .../executions` with `{id, requirement, priority}` per step, distinct
values. Send the execution's current `requirement` back alongside: that endpoint takes the whole
execution representation, and both fields reset when omitted. This is honoured from **Keycloak 25**
onward; on 24 and older a tied level cannot be reordered through the API at all, and the executions
have to be deleted and re-added in the order you want.

## Path 1 — `importAuthenticationFlow` (one shot, correct by construction)

The `keycloak-atomic-auth-flows`<!-- relink https://github.com/p2-inc/keycloak-atomic-auth-flows when public --> extension's
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
- [ ] **Every level is bucket-pure** — no level mixes `ALTERNATIVE` with `REQUIRED`/`CONDITIONAL`,
      or the alternatives there were silently erased. Check per parent, not across the whole tree.
      See "Shape" above.
- [ ] Every `CONDITIONAL` sub-flow contains an enabled condition step, or it never runs at all.
- [ ] The flow is bound to the surface the intent names (realm `browser`, a client override, or the
      IdP's post-broker/first-broker login flow — these are different surfaces).
- [ ] Behaviour verified by an actual login, not by reading configuration back. Order bugs are
      invisible in config and obvious at the login screen.
