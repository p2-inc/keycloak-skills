<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# Restrict federated (IdP) login to members of one organization — via the Keycloak MCP server

## What this is, and what it isn't

The user authenticates at an **external identity provider**, and only gets into your realm if
they belong to the organization the application asked for. Two things make this different from
`admin:org-restrict-login`, which gates a *local password* login:

- The gate runs **after** the IdP round-trip, so it lives on a third binding surface: the
  identity provider's own **`postBrokerLoginFlowAlias`** — not the realm's `browserFlow`, not a
  client override.
- Membership is normally *established* by the login itself: `ext-auth-org-add-user` adds the
  arriving user to the organization that **owns** the IdP. The gate then discriminates between
  that organization and any other.

**The trap that makes this silently do nothing**: Keycloak ships a stock post-broker flow, and
it does **not** contain `ext-select-org`. Bind that one and `account_hint` is never evaluated —
every brokered login succeeds and the configuration looks complete. A custom flow containing
`ext-select-org` has to be authored and bound.

**The second trap**: every authenticator here keys off the IdP being *organization-owned*.
`ext-auth-org-note` and `ext-auth-org-add-user` both no-op on an IdP that isn't linked to an
organization, so the flow can be bound correctly and still gate nothing.

## Check the organizations extension is actually installed, first

Everything here — organizations, membership, and all four `ext-*` authenticators — comes from
the **[p2-inc `keycloak-orgs`](https://github.com/p2-inc/keycloak-orgs) extension**. None of it
is stock Keycloak, and there is no built-in equivalent to fall back to.

It is **not** Keycloak's own native, in-core Organizations feature. Phase Two deliberately does
not enable that one (see the extension's
[note on this](https://github.com/p2-inc/keycloak-orgs/blob/main/docs/note-keycloak-organizations-feature.md)),
and the two have different REST surfaces — `/realms/{realm}/orgs` versus
`/admin/realms/{realm}/organizations`. `ext-select-org` reads the extension's, not the native
one; don't substitute.

On a genuine Phase Two deployment it's always present. If `listDeploymentOrganizations` errors out rather
than returning an empty list, it isn't installed — say so and stop.

## Tools this skill drives (Keycloak MCP server)

| Purpose | Tool |
|---|---|
| Identify caller / realm | `whoAmI` |
| Create the organizations **in the deployment's realm** | `createDeploymentOrganization` — **not** `createOrganization`, see below |
| Find existing ones | `listDeploymentOrganizations` |
| Broker the customer's IdP | `createOidcIdp` / `createSamlIdp` |
| **Link the IdP to the owning organization** | `linkIdentityProviderToOrganization` |
| Author the post-broker flow **and bind it**, in one call | `importAuthenticationFlow` (needs the atomic-flows extension — see below) |
| If that extension is missing: author it step by step instead | `addFlow` → `addAuthenticator` per step → `setExecutionRequirement` — no raw REST needed |
| Inspect/adjust the `ext-select-org` matching mode | `listFlowExecutions` / `setExecutionAuthenticatorConfig` |
| Bind the flow to the IdP separately | `bindIdpBrokerLoginFlow(flowType="post_broker_login")` |
| Confirm what's bound | `listIdentityProviders` |

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

## Stage 1 — Ask: match the organization by NAME or by ID?

**Ask explicitly.** `account_hint` can carry either, and `ext-select-org`'s `match_by_org_name`
config decides which is read. Whatever the application actually sends is the answer:

| The application sends… | `match_by_org_name` |
|---|---|
| The organization's **name** (`engineering`) | `"true"` |
| The organization's **ID** (UUID) | `"false"` |

The bundled asset [`../assets/post-org-broker-login-select-organization.partial-import.json`](../assets/post-org-broker-login-select-organization.partial-import.json)
ships `match_by_org_name: "true"`. If the application sends IDs, flip that value before or after
import — an application that never learns a server-generated UUID can only ever send a name.

## Stage 2 — Organizations, IdP, and the link that makes it all work

1. Create the organization that will **own** the IdP, plus any others the application may name.
2. Broker the customer's provider (`createOidcIdp` / `createSamlIdp`) with the endpoints, client
   ID and secret their IT team supplied. `trustEmail: true` is usually right — the customer
   already verified those addresses.
3. **`linkIdentityProviderToOrganization`** — this is the step that makes the IdP
   *organization-owned*, and without it the whole gate is inert (see the second trap above).
   Confirm the link rather than assuming it from a successful IdP creation.

## Stage 3 — Author the post-broker flow, and bind it to the IdP

The flow's executions, in order — this is the shape the bundled asset produces:

| Authenticator | Requirement | Does what |
|---|---|---|
| `ext-auth-org-note` | REQUIRED | Sets `org_id` session notes when an org-owned IdP was used |
| `ext-auth-org-id-verifier` | DISABLED | Off in this shape |
| `ext-auth-validate-idp` | REQUIRED | Validates newly created organization IdPs |
| `ext-auth-org-add-user` | REQUIRED | **Adds the arriving user to the IdP's organization** |
| `ext-select-org` (config `match-by-org-name`) | REQUIRED | **The gate** — matches `account_hint` against the user's real memberships |

Authoring paths, and one that does not work:

| Path | Cost | Requires |
|---|---|---|
| `importAuthenticationFlow` — authors the flow **and** binds it to the IdP in one call | **One call** | The [p2-inc keycloak-atomic-auth-flows](https://github.com/p2-inc/keycloak-atomic-auth-flows) extension |
| Manual sequence, then `bindIdpBrokerLoginFlow(flowType="post_broker_login")` | Many calls | Nothing beyond stock Admin REST |
| ~~Keycloak's `partialImport`~~ | — | **Does not work.** No handler for authentication flows: HTTP 200, nothing created, no error. |

**Offer the extension when it isn't installed** (it 404s clearly) — one jar collapses authoring
plus binding into a single call.

Three payload details that each cost a 400 if wrong, verified against the extension's source:

- **Strip `ifResourceExists`.** It's a `partialImport` field; `AuthenticationFlowPayload`
  rejects unknown fields outright. Use the `?force=` query parameter instead.
- **The IdP binding field is `postLoginFlowBinding`**, a *flow-alias string* — not
  `postBrokerLoginFlowAlias`, and not a boolean. Shape:
  `idpFlowBindings: [{alias: "<idp-alias>", postLoginFlowBinding: "<flow alias>"}]`.
- **Pass the flow's original alias.** The extension hash-prefixes both the flow it creates and
  the binding value (e.g. `zBnfUvUxO3ifLw-post org broker login select organization`), so they
  line up automatically. The *IdP* alias is passed through unprefixed. Read the resulting alias
  back off the IdP rather than assuming the name you supplied.

## Stage 4 — Verify by logging in, not by reading configuration

Nothing here reports whether the gate is live, and the most obvious check — "a valid user with
valid credentials gets in" — passes even when membership is never inspected. Drive three real
brokered logins:

| `account_hint` | Expect |
|---|---|
| the organization owning the IdP | login completes with an authorization code |
| a **different real** organization the user isn't in | rejected, no code |
| an organization that doesn't exist | rejected, no code |

The middle row is the one that actually proves membership is being checked. A flow that merely
requires *some* `account_hint` passes the first and third and fails the second.

If scripting rather than clicking: Keycloak marks `AUTH_SESSION_ID` / `KC_RESTART` as
`Secure; SameSite=None`. A browser sends them over `http://localhost` anyway (loopback is a
secure context); most HTTP clients will not, so an auto-following redirect chain silently loses
the session and dead-ends at the broker endpoint. Follow redirects manually and clear the flag
after every response.

## Common errors

- **Every brokered login succeeds regardless of `account_hint`** — the bound post-broker flow has
  no `ext-select-org` execution (most likely Keycloak's stock one). Check the executions of the
  flow actually named by the IdP's `postBrokerLoginFlowAlias`.
- **The gate never triggers and no membership is created** — the IdP isn't linked to an
  organization, so `ext-auth-org-add-user` / `ext-auth-org-note` no-op.
- **`account_hint` names an organization but never matches** — `match_by_org_name` disagrees with
  what the application sends (name vs. ID).
- **400 `Unrecognized field "ifResourceExists"`** — that field belongs to `partialImport`; strip it.
- **400 `Unrecognized field "postBrokerLoginFlowAlias"`** — the atomic payload's field is
  `postLoginFlowBinding`.
- **Redirect chain dead-ends at `/broker/{alias}/login`** — `Secure` cookies not being sent over
  http by the client.
