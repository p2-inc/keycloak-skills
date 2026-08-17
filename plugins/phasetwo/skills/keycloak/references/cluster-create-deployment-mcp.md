# Creating a Phase Two deployment (a hosted Keycloak realm) — via the Keycloak MCP server

This guides a user, one step at a time, through creating a **deployment** — a hosted Keycloak
realm — inside an **existing, ACTIVE Phase Two dedicated cluster**, using the Keycloak MCP
server. The end state: a new, empty realm, with the user pointed at what to do in it next.

## The translation to make explicit before doing anything

Several requests that don't mention "deployment" or "realm" at all actually resolve to this
capability, because in Keycloak **the realm is the unit of security isolation**:

- "I want to secure an application in my cluster"
- "I want a bounded security context" / "an isolated security context"
- "give this app its own tenant" / "a separate environment for staging vs production"
- "I don't want app A's users/admins/roles to be able to touch app B's"

A realm is a hard boundary: separate users, separate clients, separate roles and role mappings,
separate sessions, separate admin permissions, separate everything. There is no lighter-weight
"security context" primitive inside Keycloak that gives partial isolation for one app within a
shared realm — a client in a realm can, by default, be administered by anyone with rights over
that realm, and its users are that realm's users. If the isolation the user wants is *real* (they
don't want app A's realm-admin touching app B, or app A's user pool visible to app B), the
answer is: **each app that needs that boundary gets its own deployment.**

If the isolation they want is weaker — just "app B shouldn't see app A's data", handled at the
application layer, with both apps fine sharing one realm's user base — say so and suggest a
shared deployment with one client per app instead of automatically spinning up a new realm. Ask
if it's unclear which they mean; don't assume "secure" always means "isolate at the realm level".

## Relationship to cluster setup

- **No cluster, or not sure one exists?** Use `admin:cluster-setup` first. This assumes that
  flow's Stage 1–3 are already done (an ACTIVE cluster, owned by an organization, that you have
  access to). If `listClusters` comes back empty, that's where to send the user.
- **Cluster exists but this is the very first deployment being created right after provisioning
  it?** Either path works — `admin:cluster-setup`'s Stage 6 covers that inline. This is for every
  other case: an Nth deployment, or a deployment created independently of any cluster-creation
  conversation.
- **After the deployment exists**, it's an empty realm — say so plainly, and that hardening it
  (password policy, login flows, IdP federation, client registration) is separate follow-on work
  this router doesn't cover yet.

## Core operating principle: guide every line, prompt for every value

- **Do one step at a time.** Explain what the step does and what happens next, then do it.
- **Never invent values.** The cluster and the deployment name are the user's — ask and wait.
- **Confirm the isolation is real before creating anything**, per the translation above, so a
  request for "a bounded security context" doesn't turn into an unwanted proliferation of realms
  when a shared one with separate clients would have served the actual need.
- **Realm defaults to `self`.** Every tool's `realm` argument can be omitted — it defaults to the
  realm the caller authenticated to. Only pass it if the user is operating cross-realm.

## Tools this skill drives (Keycloak MCP server)

| Purpose | Tool |
|---|---|
| Identify caller | `whoAmI` |
| Find clusters | `listClusters` |
| Cluster status | `getCluster` (must be `ACTIVE`) |
| List existing deployments in a cluster | `listClusterDeployments` |
| Check the name is free | `checkDeploymentNameAvailable` |
| Create the deployment | `createClusterDeployment` |

## Stage 1 — Establish identity and pick the cluster

1. Call `whoAmI`.
2. Find the target cluster:
   - If the user named one, resolve it via `listClusters` (match by name or ID).
   - If they didn't, call `listClusters`:
     - **none** → there is no cluster to deploy into. Hand off to `admin:cluster-setup` and stop
       here.
     - **exactly one** → use it without asking.
     - **several** → ask which one, in the same question as Stage 2's deployment name.
3. Call `getCluster` on the chosen cluster. **It must be `ACTIVE`.** If it's still
   `BILLING_SETUP`, `PENDING_PAYMENT`, or `PROVISIONING`, that's not something this capability can
   fix — explain the status and point back to `admin:cluster-setup`'s Stage 5 (poll to ACTIVE)
   rather than attempting to create a deployment that will fail.

## Stage 2 — Confirm what's actually being asked for

Before naming anything, make sure the request really calls for a *new* deployment rather than a
change to an existing one:

- If the user already has a deployment for a related app and is asking for "isolation" from it,
  confirm they mean a **separate realm**, not (for example) a role/permission change within the
  one they have — that's plain realm administration, not this.
- Call `listClusterDeployments` on the chosen cluster and mention what already exists, in case one
  of them already serves the purpose (e.g. a `staging` deployment already exists and the user just
  didn't know).

## Stage 3 — Name and create (one batched question)

1. Ask **one question**: the deployment name (lowercase; becomes the realm name — and, if several
   clusters were found in Stage 1, which cluster).
2. Confirm the name is free with `checkDeploymentNameAvailable`. If taken, suggest alternatives —
   often the app name, or `<app>-<env>` (e.g. `billing-staging`) — and re-ask.
3. Echo back what you're about to create (cluster, deployment name) and get a quick yes.
4. Call `createClusterDeployment` with the `clusterId` and `name`.
5. **The number of deployments per cluster is limited by tier.** If creation fails for that
   reason, say so plainly — the options are deleting an unused deployment or upgrading the tier
   (this is a billing conversation, hand it to the user to resolve on their own via the dashboard
   or support).

## Verify and hand off

Confirm with the returned **`deploymentId`** and **`name`** (= `deploymentRealm` elsewhere). Then
say plainly: this is an empty realm, and that registering an app against it, hardening its login,
or federating an external IdP are all separate follow-on tasks this router doesn't cover yet —
offer to file a gap issue the same way Step 1's "No intent matches" does, if the user wants to
continue right into one of those.

## Common errors

- **`listClusters` returns empty** — no cluster exists yet; use `admin:cluster-setup`.
- **`getCluster` is not `ACTIVE`** — creation will fail; the cluster is still provisioning or
  awaiting payment. Point to `admin:cluster-setup`'s Stage 5, don't retry blindly.
- **`checkDeploymentNameAvailable` says taken** — suggest a variant (often `<app>-<env>`) and
  re-check.
- **`createClusterDeployment` fails on tier limits** — the cluster has hit its deployment cap for
  its tier; deleting an unused deployment or upgrading the tier are the only ways forward, and
  both are the user's call, not something to do unasked.
- **The user actually wanted a setting change, not a new realm** — see Stage 2; don't create a
  deployment reflexively just because the word "secure" appeared.
