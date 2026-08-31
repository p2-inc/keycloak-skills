<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# Restrict login to members of one organization — via the Keycloak MCP server

## What this is, and what it isn't

This is a **membership gate**, not domain-based routing: only someone who is already a member of
a specific organization can complete login. It is the deliberate counterpart to
`admin:corporate-sso`'s caveat — that intent auto-*routes* a user to their company's IdP by email
domain but never *restricts* who can log in; this one restricts, using `Org Browser Flow` (the
realm's built-in org-aware flow) or one of its custom variants, plus the `ext-select-org`
authenticator.

**The trap `bindRealmAuthenticationFlow` itself warns about**: binding `Org Browser Flow`
realm-wide does **not**, by itself, force every plain username/password login to require
organization membership. The org-selection/membership check inside the flow only runs when the
authorization request carries **`prompt=select_account`** or **`account_hint=<value>`** — a
client has to actually send one of those. A login with neither parameter skips the org-selection
step entirely and behaves like an ordinary login. If the goal is "every login to this client must
be gated by org membership," confirm the client is actually configured to send `account_hint` or
`prompt=select_account` — binding the flow is necessary but not sufficient.

## Check the organizations extension is actually installed, first

**Everything here depends on the
[p2-inc `keycloak-orgs`](https://github.com/p2-inc/keycloak-orgs) extension** — organizations
themselves, membership, and the `ext-select-org` authenticator that performs the gate. None of it
is part of stock Keycloak, and none of it can be reproduced without the extension: there is no
built-in equivalent to fall back to.

It is **not** the same thing as Keycloak's own native, in-core Organizations feature. Phase Two
deliberately does not enable that one (see the extension's
[note on this](https://github.com/p2-inc/keycloak-orgs/blob/main/docs/note-keycloak-organizations-feature.md)),
and the two have different REST surfaces — `/realms/{realm}/orgs` for the extension versus
`/admin/realms/{realm}/organizations` for native. Don't substitute one for the other.

On a genuine Phase Two hosted deployment the extension is always present. If you're unsure, a
`listDeploymentOrganizations` call erroring out (rather than returning an empty list) means it isn't
installed — say so plainly and stop, rather than working around it with the native API, which
`ext-select-org` does not read.

## Tools this skill drives (Keycloak MCP server)

| Purpose | Tool |
|---|---|
| Identify caller / realm | `whoAmI` |
| Create the organization **in the deployment's realm** | `createDeploymentOrganization` — **not** `createOrganization` |
| Find an existing organization | `listDeploymentOrganizations` |
| Look up a user in that realm | `findUser` |
| **Add the members the gate will admit** | `addDeploymentOrganizationMember` |
| Confirm who is a member | `listDeploymentOrganizationMembers` |
| Confirm which org-aware flow(s) already exist | `listAuthenticationFlows` |
| Author the flow **and bind it**, in one call | `importAuthenticationFlow` (needs the atomic-flows extension — see below) |
| Inspect/adjust the `ext-select-org` step's matching mode | `listFlowExecutions` / `setExecutionAuthenticatorConfig` |
| Bind an already-existing flow | `bindRealmAuthenticationFlow` / `bindClientAuthenticationFlow` |
| Confirm bindings | `getAuthenticationBindings` |

> **First, the terminology that makes the rest of this readable: in Phase Two a *deployment* IS a
> Keycloak realm.** One deployment == one realm, with the same name — `createClusterDeployment`'s
> returned `name` is the realm name. So "the deployment's realm" is not a realm *inside* a
> deployment; it's the same thing said twice, and `deploymentRealm` is just that name.
>
> **`createOrganization` is the wrong tool for this intent, and it fails in a way that wastes a
> whole session.** There are **two separate organization stores**, and they are not connected:
>
> | Store | Lives on | Written by | Read by |
> |---|---|---|---|
> | **Account-level** Phase Two orgs — the ones that own clusters and hold billing | the Phase Two **control plane** | `createOrganization`, `listMyOrganizations` | the control plane |
> | **Deployment orgs** — i.e. realm orgs: the `keycloak-orgs` store at `/realms/{realm}/orgs` | the **deployment's own Keycloak** (that realm) | **`createDeploymentOrganization`** | `linkIdentityProviderToOrganization`, `ext-select-org`, Home IdP Discovery |
>
> `createOrganization` only ever writes the first one, and its `realm` argument selects a
> *control-plane* realm — **not** a deployment/realm. Passing a deployment name to it **404s**,
> because no such realm exists on the control plane. An org it did create is invisible to the link
> tool, which returns `{"error": "<orgId> not found"}`. Both failures look like a bad org id rather
> than the wrong store, which is what makes this expensive to diagnose.
>
> Use **`createDeploymentOrganization`** (and `listDeploymentOrganizations` to find an existing
> one). Its returned `orgId` is what `ext-select-org` resolves against at login time, and what
> `addDeploymentOrganizationMember` takes.

## Authoring a flow: two paths, and one that does NOT work

**Keycloak's own `partialImport` endpoint cannot author authentication flows.** It has no
handler for them at all (only clients, roles, identity providers, IdP mappers, groups and
users), so an `authenticationFlows` array sent to it is **silently ignored** — HTTP 200, `added:
0`, no error of any kind. Do not use it, and do not believe a 200 from it means a flow was
created. (This is why the bundled assets are named `*.partial-import.json` — that naming
predates this discovery and is now misleading; the files themselves are still correct.)

The two paths that do work:

| Path | Cost | Requires |
|---|---|---|
| **`importAuthenticationFlow`** — authors the whole flow *and* applies bindings in one call | One call | The [p2-inc keycloak-atomic-auth-flows](https://github.com/p2-inc/keycloak-atomic-auth-flows) extension installed on the target Keycloak |
| **The component path, through MCP tools** — `addFlow` → `addSubFlow` per sub-flow → `addAuthenticator` per leaf step (passing `priority` **and** `requirement`) → `addConditional` for the conditional-OTP sub-flow → `addAuthenticatorConfig` on each `ext-select-org` step → bind | Many calls, order matters | Nothing beyond stock Admin REST — no extension |

**Both paths are MCP tool calls. Neither requires dropping to raw REST or asking the user for
credentials** — component authoring is the default, and `importAuthenticationFlow` is the one-shot
for deployments that have the extension. If it 404s, build the flow from components rather than
reporting a dead end. Offer the extension
as a real choice first — installing one jar collapses the whole sequence into a single call — but
proceed with the component tools when the user prefers that or can't install it.

**Order is load-bearing on the component path, and `addSubFlow`/`addAuthenticator`
APPEND.** With no `priority` argument, each call lands at `(last sibling's priority + 1)` — so
creating a sub-flow before its parent's other steps exist puts it first, ahead of `auth-cookie`.
Pass `priority` explicitly on every call. It's honoured only from Keycloak 25 onward (added
2024-05-29); on older versions add steps in the intended order and repair with
`raiseExecutionPriority`/`lowerExecutionPriority`, which each swap one adjacent sibling per call.
Read the order back with `listFlowExecutions` before declaring the flow done — nothing errors on
a wrong order, so it has to be checked, not assumed.

**This flow is the one with a CONDITIONAL sub-flow, so it needs `addConditional`.** A conditional
is not a single step: it's a sub-flow whose *execution* is `CONDITIONAL`, whose **first** child is
a condition authenticator, followed by the steps being gated. For the OTP branch that means
`addConditional(parentFlowAlias="<Forms Sub-Flow>", alias="<Conditional OTP>",
conditionProvider="conditional-user-configured", priority=20)`, then
`addAuthenticator(flowAlias="<Conditional OTP>", provider="auth-otp-form", priority=1,
requirement="REQUIRED")` for the gated step. `conditional-user-configured` takes no config; every
other condition (`conditional-user-role`, `conditional-user-attribute`, `conditional-client-scope`,
…) does — read its real key names with `getAuthenticatorConfigDescription` rather than guessing,
because they aren't uniform (`negate` vs `not` vs `included` for the same idea).

**Config aliases are unique per realm, not per execution.** This asset attaches
`match-by-org-name` to `ext-select-org` in *three* sub-flows. The atomic import turns that into one
shared config, but `addAuthenticatorConfig` creates one per execution and the second attach with a
repeated alias returns **409** — so give each a distinct alias (`match-by-org-name-cookies`,
`-idp`, `-forms`). Same values, different aliases.

**The atomic import hash-prefixes every alias.** The flow it creates is *not* named what the
asset says — it gets a generated prefix like `8esLlLB3D3YqVg-Org Browser Flow by Org Name`. Read
the real alias back from the tool's response or `getAuthenticationBindings`; never assume it. That
prefix is also how it stays idempotent: re-importing identical content returns **409** and creates
nothing, unless `force=true` (which replaces in place rather than duplicating).

## Stage 1 — Ask: match the organization by NAME or by ID?

**Ask this explicitly — don't guess.** `account_hint` can carry either an organization's `name` or
its `id`, and the flow has to be configured for exactly one interpretation via the
`ext-select-org` authenticator's `match_by_org_name` config key:

| The application will send… | Set `match_by_org_name` to | Asset |
|---|---|---|
| The organization's **name** (human-readable, e.g. `contoso`) | `"true"` | [`../assets/org-browser-flow-by-org-name.partial-import.json`](../assets/org-browser-flow-by-org-name.partial-import.json) |
| The organization's **ID** (UUID) | `"false"` | [`../assets/org-browser-flow-by-org-id.partial-import.json`](../assets/org-browser-flow-by-org-id.partial-import.json) |

**Both assets author a flow under the identical alias `Org Browser Flow by Org Name`** — they are
two alternative *configurations* of the same flow, not two flows that can coexist. Import
whichever one matches the answer to this question. Importing the other afterward will not quietly
switch modes: via `importAuthenticationFlow` the differing config produces a different hash and
therefore a *separate* flow (leaving the first one bound), so decide the mode up front rather
than importing both and hoping.

## Stage 2 — Confirm what's already there (usually: importing nothing is enough)

**Start here, and expect not to need an import at all.** A Phase Two Keycloak ships a built-in
**`Org Browser Flow`** that *already contains* the `ext-select-org` execution. In that case the
whole job is: set that execution's `match_by_org_name` to match Stage 1's answer
(`setExecutionAuthenticatorConfig`), then bind the flow (Stage 4). No import, no custom flow.

Call `listAuthenticationFlows`, then `listFlowExecutions` on any `Org Browser Flow` /
`Org Browser Flow by Org Name` you find, and check the `ext-select-org` execution's actual
`match_by_org_name` value — **don't assume an existing flow is configured the way you want just
because its name looks right.** Only fall through to Stage 3 if no flow with an `ext-select-org`
execution exists at all.

## Stage 3 — Author the flow (and bind it), only if Stage 2 found nothing usable

If no flow with an `ext-select-org` execution exists, call `importAuthenticationFlow` with the `authenticationFlows`
and `authenticatorConfig` arrays from whichever asset matches Stage 1's answer, **plus the binding
in the same payload** — that's the whole point of the atomic import, and it means Stage 4's
separate bind call is unnecessary on this path:

```json
{
  "authenticationFlows": [ ...from the asset... ],
  "authenticatorConfig": [ ...from the asset... ],
  "browserFlowBinding": "Org Browser Flow by Org Name"
}
```

(The asset's own `ifResourceExists` field is not part of this payload and is ignored — it was for
the `partialImport` endpoint that doesn't work for flows.) For a single client instead of
realm-wide, use `clientFlowBinding: {clientId, browserFlowBinding, directFlowBinding}`; for
per-IdP first/post-broker flows, `idpFlowBindings: [{alias, firstLoginFlowBinding,
postLoginFlowBinding}]`.

If the extension isn't installed (404), offer it — see the two-paths section above — and fall back
to the manual REST sequence only if the user declines.

To flip an already-imported flow's matching mode without re-importing, use
`setExecutionAuthenticatorConfig` on the `ext-select-org` execution instead (find it with
`listFlowExecutions` first) — set `match_by_org_name` to `"true"` or `"false"` directly. This is
usually better than importing the other asset, which creates a second, separate flow.

## Stage 4 — Bind it (only if Stage 3 didn't already)

**Skip this entirely if you bound in the import payload** — that's the normal path. This stage is
for binding a flow that already existed (built-in `Org Browser Flow`, or one imported earlier), or
for re-binding after a change.

Same two surfaces as every other flow-binding intent in this router:

| Surface | When to use it | Tool |
|---|---|---|
| Realm-wide | Every client in the realm should require org membership (when `account_hint`/`prompt=select_account` is sent) | `bindRealmAuthenticationFlow(bindingType="browser", flowAlias=...)` |
| Single client | Only one application should require it | `bindClientAuthenticationFlow` |

Use the flow's **real** alias here — if it came from `importAuthenticationFlow` that's the
hash-prefixed one, not the name in the asset.

Then confirm the client(s) that need this gate are actually configured to send `account_hint` or
`prompt=select_account` on their authorization requests — see the trap at the top of this doc.
Verify with `getAuthenticationBindings`.

## Verify by logging in, not by reading configuration

Nothing here reports whether the gate is actually active — behavior only shows up in a real login:

1. A request **without** `account_hint`/`prompt=select_account`: should behave like an ordinary
   login, unaffected by this flow.
2. A request **with** `account_hint` set to a value matching Stage 1's chosen mode (a name or an
   ID), for a user who **is** a member of that organization: should complete login normally.
3. A request **with** `account_hint` set to an org the user is **not** a member of: should be
   rejected — confirm it actually is, rather than assuming the flow enforces this correctly.

## Common errors

- **Bound the flow, but plain logins are unaffected either way** — expected if the client never
  sends `account_hint`/`prompt=select_account`; this is not a bug, see the trap at the top.
- **Importing the "by ID" asset after "by name" (or vice versa) creates a second, separate
  flow** rather than switching the mode of the first — `importAuthenticationFlow` hashes the
  payload's content into the alias it creates, so differing config produces a different hash,
  not a match against the existing one. The original flow stays bound. Use
  `setExecutionAuthenticatorConfig` on the existing `ext-select-org` execution to flip the mode
  in place instead of importing the other asset.
- **`account_hint` set to a name but `match_by_org_name` is `"false"` (or vice versa)** — the
  mismatch between what the client sends and how the authenticator interprets it is silent; check
  both explicitly with `listFlowExecutions` rather than assuming they agree.
- **A required MCP tool is missing** — report it and stop; do not switch to REST unsolicited.
