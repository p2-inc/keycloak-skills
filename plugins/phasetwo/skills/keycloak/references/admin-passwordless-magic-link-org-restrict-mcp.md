# Magic-link login restricted to one organization's members — via the Keycloak MCP server

## What this is, and what it isn't

Magic-link login (open an emailed link, you're in, no password) **combined with** a membership
gate: only someone who belongs to the organization named in the request's `account_hint` ever
receives the link. Neither half is new by itself — `admin-passwordless-magic-link-mcp.md` covers
plain magic-link, `admin-org-restrict-login-mcp.md` covers gating a *password* login — but the
built-in `magic link` flow has no `ext-select-org` step, and `Org Browser Flow` has no magic-link
step, so combining them needs a **custom flow** that neither reference's binding target covers.

**What makes this different from just adding a step**: the membership check has to run **before**
any mail goes out. Reveal "an account exists here" only after confirming the requester belongs to
the hinted organization — never before. The flow below does this by collecting just an identifier
first (setting it in the auth-session context, no credential check yet), running the org check
against that, and only then reaching the magic-link step itself.

## Tools this skill drives (Keycloak MCP server)

| Purpose | Tool |
|---|---|
| Identify caller / realm | `whoAmI` |
| Create the organization **in the deployment's realm** | `createDeploymentOrganization` — **not** `createOrganization`, see below |
| Find an existing one | `listDeploymentOrganizations` |
| Add a member | `addDeploymentOrganizationMember` (after `findUser`) — **not** `addOrganizationMember`, which is account-level |
| Confirm no flow already does this | `listAuthenticationFlows` |
| Author the flow **and bind it**, in one call | `importAuthenticationFlow` (needs the atomic-flows extension — see below) |
| Inspect/adjust the `ext-select-org` step's matching mode | `listFlowExecutions` / `setExecutionAuthenticatorConfig` |
| Configure outgoing mail | `setSmtpSettings` |
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
> one). Its returned `orgId` is what `linkIdentityProviderToOrganization` expects.

## Prerequisite: the keycloak-orgs extension

Same dependency as `admin-org-restrict-login-mcp.md`: the real
**[p2-inc `keycloak-orgs`](https://github.com/p2-inc/keycloak-orgs)** extension, not Keycloak's
native Organizations feature. If `listDeploymentOrganizations` errors rather than returning an empty list,
it isn't installed — say so and stop.

## Stage 1 — Ask: match by organization NAME or ID?

Same question as every other `ext-select-org` intent: `account_hint` can carry either, and
`match_by_org_name` decides which is read. Ask what the application actually sends — don't guess.

## Stage 2 — The organization and its member(s)

Create the organization, then add each intended member. Confirm membership actually stuck rather
than assuming a successful add call means it did.

## Stage 3 — Author the flow (and bind it)

Confirm with `listAuthenticationFlows` that no flow already does this. `importAuthenticationFlow`
authors and binds it in one call, but needs the atomic-flows extension — 404 if it's missing.
**That is not a dead end — component authoring is the default path.** Build it through MCP tools,
no raw REST and no credentials needed from the user: `addFlow` for the top
level, `addSubFlow` for the forms sub-flow, `addAuthenticator` for each
leaf step below — **in the order the table below gives**, passing `priority` explicitly on every
call since both append when it's omitted — then `setExecutionRequirement` on each and
`setExecutionAuthenticatorConfig` for the two that need config.

```json
{
  "authenticationFlows": [ /* from ../assets/select-organization-magic-link.partial-import.json */ ],
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
| `ext-magic-form` | REQUIRED | `ext-magic-create-nonexistent-user=false` | Only reached once membership passed. `false` here for the same reason plain magic-link sets it — the factory default (`true`) would provision an account for anyone reaching this point, and with the gate in front, that's a real account attached to an unlisted address. |

Putting `ext-magic-form` before `ext-select-org` would send mail regardless of membership and
defeat the entire point of gating — this is the one thing not to improvise around.

Read the real, hash-prefixed alias back from `importAuthenticationFlow`'s response rather than
assuming the asset's name — same trap as every other atomic-flows intent. (The manual-sequence
path doesn't have this issue: you choose the alias yourself.)

## Stage 4 — Realm mail settings

`setSmtpSettings` — same silent-failure trap as plain magic-link: an unconfigured or misconfigured
realm looks identical to a working one from the caller's side. Verify by checking what actually
left (a capture point in test contexts), not by trusting a success response.

## Stage 5 — The account_hint trap, again

`ext-select-org` only runs when the request carries `account_hint` or `prompt=select_account` — a
request with neither skips the gate (and, on this flow specifically, skips the identifier-collection
step entirely too). Confirm the application actually sends one of those two parameters on every
login that should be gated.

## Stage 6 — Verify by logging in, not by reading configuration

1. A member with the correct `account_hint`: should receive mail with an action-token link:
   completing it returns an authorization code.
2. A non-member with the same `account_hint`: should receive **no mail at all** — check outgoing
   mail directly, since the identifier-collection step's page response may look identical either
   way (same anti-enumeration logic as plain magic-link).
3. An `account_hint` matching no real organization, for a genuine member of some other
   organization: also rejected — this is what proves membership is actually checked, not merely
   the presence of some `account_hint` value.

## Common errors

- **Everyone gets mail regardless of membership** — executions are out of order, or the bound flow
  is missing `ext-select-org` entirely. Re-check Stage 3.
- **Nobody gets mail, even members** — `setUserInContext` missing/false on the username-note step,
  or realm SMTP unconfigured (Stage 4).
- **`account_hint` set to a name but `match_by_org_name` is `"false"` (or vice versa)** — check both
  explicitly with `listFlowExecutions` rather than assuming agreement.
- **A required MCP tool is missing** — report it and stop; do not switch to REST unsolicited.
