# Provisioning a Phase Two dedicated cluster — via the Keycloak MCP server

This guides a user, one step at a time, through creating a **dedicated Phase Two hosted
Keycloak cluster** using the Keycloak MCP server. The end state: an **ACTIVE** cluster owned by
one of the user's organizations, optionally with its first **deployment** (a Keycloak realm)
created.

> **Requires the Phase Two SaaS bundle.** The cluster tools only work against a Keycloak running
> the internal Phase Two clusters extension — not the public keycloak-orgs plugin. If
> `listClusterRegions` returns a 404 (Stage 3), this server can't provision clusters — stop and
> say so.

> **If the cluster already exists** and the user just wants another deployment (realm) in it — or
> phrases it as wanting to "secure an app" or give it "a bounded security context" — that's
> Stage 6 of this flow in miniature, generalized: use `admin:cluster-create-deployment` instead of
> restarting this whole flow.

## Core operating principle: guide every line, prompt for every value — never pay

The person running this may be doing it for the first time. So:

- **Do one step at a time.** Explain what the step does and what happens next, then do it.
- **Keep the journey light.** Don't ask for anything already provided; batch the still-missing
  values into a SINGLE question; don't narrate intermediate tool calls.
- **Never invent values.** Cluster names, regions, and the owning org are the user's — ask and
  wait.
- **NEVER enter or complete payment.** `createCluster` returns a Stripe checkout link. If a
  browser tool is available, opening a tab to that link for the user is fine (Stage 4) — but stop
  there. Filling in card or billing details, or clicking to submit/pay, is the human's step,
  always, with or without a browser tool available.
- **NEVER delete a cluster, deployment, or realm.** Not with a tool, not with `curl`, not with the
  Admin REST API — there is no path to it here and you must not go looking for one. `deleteCluster`
  refuses every call, and no tool deletes a deployment or a realm at all. Deletion is irreversible
  and takes every application authenticating against the target offline, so it is the human's step,
  in the console. See "Deleting is console-only" below.
- **Realm defaults to `self`.** Every tool's `realm` argument can be omitted — it defaults to the
  realm the caller authenticated to. Only pass it if the user is operating cross-realm.

## Tools this skill drives (Keycloak MCP server)

| Step | Tool | Purpose |
|---|---|---|
| Identify caller | `whoAmI` | Who am I + which realm my token is from |
| Find orgs | `listMyOrganizations` | Organizations the caller belongs to (the cluster needs an owner) |
| Resolve org | `getOrganization` / `listOrganizations` | Resolve a named/UUID org if the user specified one |
| Regions | `listClusterRegions` | Available regions; also the capability probe (404 = no SaaS bundle) |
| Name check | `checkClusterNameAvailable` | Confirm the chosen name is free (lowercase alphanumeric, ≤63 chars) |
| Create + pay | `createCluster` | Create the cluster; returns the **Stripe checkout link** |
| Poll status | `getCluster` | Watch status until `ACTIVE` (BILLING_SETUP → PENDING_PAYMENT → PROVISIONING → ACTIVE) |
| First realm | `checkDeploymentNameAvailable`, `createClusterDeployment` | Optionally create the first deployment (a realm) |
| Custom domain | `updateClusterDomain` | Optionally set a custom domain |
| Deletion | — | **Not available.** `deleteCluster` always refuses; there is no deployment- or realm-delete tool. Console-only, see below |

## Stage 1 — Establish identity

Call `whoAmI`. Tell the user who they're authenticated as and which realm the token came from.
This is the realm the cluster calls run against (omit `realm` on later calls to use it).

## Stage 2 — Pick the owning organization

Every cluster is owned by an organization.

- If the user **named an org**, resolve it: `getOrganization` for a UUID, or `listOrganizations`
  to match a name.
- Otherwise call `listMyOrganizations`:
  - **exactly one** → use it without asking.
  - **several** → don't ask yet; fold the choice into the single question in Stage 3.
  - **none** → stop and explain they need an organization to own the cluster first.

## Stage 3 — Name, region, tier, billing (one batched question)

1. Call `listClusterRegions` **first**. **If it errors (e.g. HTTP 404), STOP immediately** — this
   Keycloak does not serve the Phase Two clusters API (it needs the SaaS bundle, not the public
   orgs plugin). Explain that and end.
2. Ask the user **one question** covering everything still missing:
   - **which organization** (only if Stage 2 found several),
   - the **cluster name** — lowercase alphanumeric, max 63 chars. If the user's suggestion is
     invalid (e.g. contains a hyphen or uppercase), propose a corrected variant rather than just
     rejecting it.
   - the **region** — show the options returned by `listClusterRegions`.
   - the **tier** — `starter`, `premium`, or `enterprise` (default `starter`).
   - the **billing period** — `monthly` or `annual` (default `monthly`). **Note: the starter tier
     is monthly-only** — if they pick starter + annual, explain and switch to monthly.
3. Confirm the name is free with `checkClusterNameAvailable`. If taken, suggest alternatives and
   re-ask.

## Stage 4 — Create the cluster and hand off payment

1. Echo back what you're about to create (name, region, tier, billing, owning org). Get a quick
   yes.
2. Call `createCluster` with `name`, `region`, `tier`, `billingPeriod`, and `orgId` (from
   Stage 2).
3. The tool returns a **`checkoutLink`**. If a browser tool is available in this session, open a
   new tab and navigate it to the `checkoutLink` so the checkout page is already on screen — this
   is strictly a convenience (saves a copy-paste) and changes nothing about who completes the
   purchase. Then tell the user:
   > I've opened the Stripe checkout in a browser tab. Please complete the checkout there — the
   > cluster stays in BILLING_SETUP until payment completes, then it provisions automatically.

   If no browser tool is available, present the `checkoutLink` prominently instead and tell the
   user to open it themselves.

   **In either case, do not interact with the checkout page beyond opening it** — no filling in
   card/billing fields, no clicking pay/submit, no reading back card details. Opening the tab is
   as far as this goes; completing the purchase is the human's step, always. If the checkout page
   requires an action beyond loading (e.g. a login wall before the payment form appears), stop and
   let the user take it from there rather than clicking through it.

## Stage 5 — Poll to ACTIVE

After the user confirms they've completed checkout, poll `getCluster` with the cluster's
`clusterId` and report progress as the status advances: `BILLING_SETUP → PENDING_PAYMENT →
PROVISIONING → ACTIVE`. Only proceed once it's **ACTIVE**. If it stalls in `BILLING_SETUP`,
payment hasn't completed — point the user back to the checkout link.

## Stage 6 — First deployment (optional)

A cluster on its own has no realm yet. Ask whether the user wants a first **deployment** (a
Keycloak realm) created now.

- If yes: ask for a deployment name (lowercase; becomes the realm name), confirm it with
  `checkDeploymentNameAvailable`, then call `createClusterDeployment` with the `clusterId` and
  name. The cluster must be **ACTIVE** for this to succeed.
- Record the returned **`deploymentId`** and **`name`** (= `deploymentRealm`) — these are the
  coordinates other Keycloak/Phase Two work (IdP federation, client registration) needs next.

## Stage 7 — Custom domain (optional)

If the user wants the cluster served from their own domain, call `updateClusterDomain` with the
`clusterId`, the existing `name` (names can't change), and the new `domain`. (DNS/verification
steps happen outside this skill.)

## Verify and summarize

Finish with a short summary: cluster **ID, name, region, owning org, tier, status**, and the
first **deployment** (id + name) if one was created.

## Re-running / fixing

- To abandon a cluster, don't try to delete it — see "Deleting is console-only" below and hand the
  user the console link.
- If `createCluster` reported multiple organizations, re-run it with an explicit `orgId`.

## Deleting is console-only

Deleting a **cluster**, a **deployment**, or a **realm** is denied over MCP, for every caller,
whatever the arguments. This is a deliberate block, not a missing feature and not a permissions
problem to work around:

- `deleteCluster` returns `{"denied":true,...}` and never calls the Phase Two API. The underlying
  DELETE was removed from the server, so retrying, passing a different `clusterId` or `realm`, or
  calling it as a different user changes nothing.
- There is **no** MCP tool that deletes a deployment or a realm. That absence is the design, so
  don't report it as a gap or file it as a missing intent.
- Do **not** substitute the Phase Two API, the Keycloak Admin REST API, `curl`, or any other tool.
  A deployment is a realm (see `cluster-create-deployment-mcp.md`), so a realm delete destroys every
  user, client, and flow in it, and every application authenticating against it stops working.

What to do instead: say plainly that deletion is console-only and why, then point the user at
`https://dash.phasetwo.io/clusters` to do it themselves, or at support@phasetwo.io. Stop there —
don't offer a workaround, and never report a deletion as done.

## Common errors

- **`listClusterRegions` 404** — the Phase Two clusters API isn't on this server (needs the SaaS
  bundle). Cluster provisioning is not possible here; stop.
- **"You belong to multiple organizations"** — pass `orgId` explicitly (Stage 2).
- **Stuck in BILLING_SETUP** — the Stripe checkout hasn't been completed in a browser; re-share
  the checkout link.
- **`createClusterDeployment` fails** — the cluster must be `ACTIVE` first; finish Stage 5 before
  Stage 6.
- **starter + annual rejected** — the starter tier is monthly-only; use monthly or a higher tier.
