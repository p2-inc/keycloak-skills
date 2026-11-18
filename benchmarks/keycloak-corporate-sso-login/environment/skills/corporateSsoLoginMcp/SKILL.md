---
name: corporateSsoLoginMcp
description: >-
  Set up corporate SSO / enterprise SSO on a Phase Two hosted Keycloak — send a user to their
  own company's identity provider based on the domain of the email address they type, while
  everyone else keeps password login — using the Keycloak MCP server. Use this whenever someone
  says "I want corporate SSO login", "we need enterprise SSO", "SSO for our customer", "let our
  customer log in with their company account", "log in with my company's SSO automatically",
  "redirect to my corporate IdP", "authenticate to my corporate IdP", "home realm discovery",
  "IdP discovery by email domain", "onboard an enterprise customer's SSO", or "associate a
  corporate IdP with organization login" — even if they only say "corporate SSO". Covers the
  deployment organization + domain + linked-IdP mechanism that performs the discovery, the
  `homeIdp` / `homeIdp with orgs-check` flows built on `ext-auth-home-idp-discovery`, why an
  identity-provider-redirector execution is the wrong answer, and how to verify the routing by
  actually logging in. Not user federation (connectingUserStore), not plain identity brokering
  with a login-page button (connectingIdentityProvider), and not binding
  organization/passwordless flows generally (bindingAuthenticationFlow).
---

<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# Corporate SSO by email domain — via the Keycloak MCP server

## Step 0 — Is the MCP surface actually here?

**Do this before any tool call.** Check your tool list once, now, for:

`whoAmI` · `createDeploymentOrganization` · `linkIdentityProviderToOrganization` · `importAuthenticationFlow` · `bindRealmAuthenticationFlow`

- **All present** → say "Using the Keycloak MCP tools", then follow this skill as written.
- **Any missing** → say "Keycloak MCP tools unavailable in this session (missing: …) — using the
  Keycloak admin REST API instead", then **keep reading**. Every stage below still applies: the
  behaviour it configures is a property of Keycloak, not of the transport. Only the calls change —
  carry out each stage against the admin REST API with an admin token: organizations at
  `$KC_URL/realms/{realm}/orgs`, everything else at `$KC_URL/admin/realms/{realm}/...`. If the
  sibling skill `corporateSsoLoginRest` is loaded, use its exact REST recipes.

Decide once, here. Do not call an MCP tool to discover whether it exists, and do not alternate
between the two paths afterwards — discovering the gap a step at a time is measurably more
expensive than committing up front.

Say which path you took either way: a run that silently swaps tooling is indistinguishable from
one that never had the tools.

## What is actually being asked for

"I want corporate SSO login" decomposes into three requirements. Only the first is obvious,
and the third rules out the tempting answer:

1. **Broker the customer's identity provider** so their staff authenticate there, not here.
2. **Route to it automatically, by email domain** — a user typing `someone@customer.example`
   must never see your password form or a menu of providers.
3. **Leave everyone else alone** — your own staff, and every other customer, keep the login
   they already had.

Keycloak has an **Identity Provider Redirector** execution that sends users to a provider with
no prompt. It is not domain-based discovery: it forwards *everyone* (or only when the client
passes `kc_idp_hint`, which a plain browser login does not). It satisfies 1 and 2 and breaks 3.
Do not offer it as the answer to this request.

## Check the organizations extension is actually installed, first

Everything here — organizations, domains, and the IdP-linking that makes discovery work — comes
from the **[p2-inc `keycloak-orgs`](https://github.com/p2-inc/keycloak-orgs) extension**. It is
not part of stock Keycloak (Keycloak's own native, in-core Organizations feature is a *different*
thing — Phase Two deliberately does not enable it; see the extension's own
[note on this](https://github.com/p2-inc/keycloak-orgs/blob/main/docs/note-keycloak-organizations-feature.md)).
On a genuine Phase Two hosted deployment this is always present. If you're unsure, `whoAmI`
followed by a call like `listDeploymentOrganizations` erroring out (rather than returning an empty list)
is a sign the extension isn't installed on this server — say so plainly rather than assuming the
MCP tools below will work.

## Tools this skill drives (Keycloak MCP server)

| Purpose | Tool |
|---|---|
| Identify caller / realm | `whoAmI` |
| Create the customer's organization **in the deployment's realm** | `createDeploymentOrganization` — **not** `createOrganization`, see below. **Pass the customer's email domain in `domains`**: that is the list discovery matches, and no MCP tool adds one later |
| Find an existing one | `listDeploymentOrganizations` |
| Create the corporate IdP | `createOidcIdp` / `createSamlIdp` |
| **Link the IdP to the organization** | `linkIdentityProviderToOrganization` — pass the same `domains` (see below) |
| See what flows exist | `listAuthenticationFlows` |
| Author a flow from an asset, and bind it | `importAuthenticationFlow` |
| Bind an existing flow | `bindRealmAuthenticationFlow` / `bindClientAuthenticationFlow` |
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

Capture **`deploymentId`** and **`deploymentRealm`** and reuse them on every call.

> **Drive this through the MCP tools.** If a required tool is unavailable in this deployment,
> say so and stop. Do **not** silently substitute Admin REST calls — an unreported switch hides
> the fact that the tooling is incomplete, and leaves the user unable to reproduce what you
> did. Only fall back to REST if the user confirms this is not a Phase Two realm.

## The hard prerequisite — establish this first

**Discovery matches on the organization's own domain list.** The discoverer finds the
organization whose `domains` hold the domain of the typed address, then forwards to the IdP
linked to that organization. So the first question is:

> **"Is the company modelled as an organization in this realm, holding the customer's email
> domain, and is the IdP linked to it?"**

Two corollaries that save a long debugging session:

- **Domain verification is irrelevant to routing** unless the discovery execution's config sets
  `requireVerifiedDomain` to `true`. It defaults to `false`, and the bundled assets leave it
  off. An unverified domain routes perfectly well.
- **The link's `domains` do not route anything on their own.** `linkIdentityProviderToOrganization`
  writes them to the IdP as `home.idp.discovery.domains`. Discovery reads that only when the realm
  allows several IdPs per organization (`_providerConfig.orgs.config.multipleIdps`), and then only
  to choose among them. An organization created without the domain routes nobody, even when the
  link carries it. Pass the domain to `createDeploymentOrganization` first; repeating it on the
  link costs nothing. If a tool description says discovery matches the link's domains, the
  description is wrong: measured on Phase Two's 26.8.2 image.

Since keycloak-orgs 0.199 the organization's domains also gate first login: the realm's
`first broker login` flow carries a required `ext-auth-org-domain-fbl-verifier`, so an IdP linked
to an organization can create an account only for an email at one of that organization's domains
(GHSA-gvcc-4vw2-6wvr).

Two things must both be true, and each fails silently on its own. The flow in the next section
must also be bound.

| Missing | Symptom |
|---|---|
| The organization does not hold the customer's email domain | Discovery has nothing to match: a customer address gets "Invalid username or password.", even if the link carried the domain |
| The IdP is created but **not linked** to the organization | The organization has no IdP to forward to: the same "Invalid username or password." page |

The second is the one that gets skipped: **creating an IdP does not associate it with any
organization.** `linkIdentityProviderToOrganization` takes the `orgId`, the `idpAlias`, and the
organization's email `domains`. Without that call, Home IdP Discovery will never find the IdP
for that domain, no matter how correct everything else is.

Confirm the link exists before moving on — do not assume it from a successful IdP creation.

**"Verified" is real DNS domain-ownership proof, not a flag you set — and triggering it is
deliberately not exposed here.** Adding a domain to an organization (via `createDeploymentOrganization`'s
`domains` argument) does not mark it verified. The extension verifies ownership by checking for a
TXT record at `_org-domain-ownership.<domain>` holding a value derived from the domain and the
organization's ID, and only flips `verified` to `true` once that DNS record is found. **This is a
Phase Two-managed process, not something this skill (or any MCP tool) triggers.** Use
`listDeploymentOrganizationDomains` to check a domain's current status and get the record it
needs, then direct the customer to Phase Two's own process for getting it verified. Verification
is not a prerequisite for this intent: an unverified domain routes with the bundled flows.

## Which flow to bind

| The user also wants… | Flow | Asset |
|---|---|---|
| Just the corporate-IdP redirect, by email domain | **`homeIdp`** | [`assets/home-idp.partial-import.json`](assets/home-idp.partial-import.json) |
| The redirect **and** to be treated as a member of that organization | **`homeIdp with orgs-check`** | [`assets/home-idp-with-orgs-check.partial-import.json`](assets/home-idp-with-orgs-check.partial-import.json) |

Both drive the redirect through the **`ext-auth-home-idp-discovery`** authenticator (config alias
`home-idp-discovery`). This is what actually performs the org/domain/link lookup described above
— confirm it's present in whichever flow you bind, not just that *a* custom flow exists. The
realm's built-in `browser` flow has none: with the organization and link in place and no such
flow bound, a customer address still gets the ordinary password form.

Both are custom flows. Confirm with `listAuthenticationFlows`; if the one you need is missing,
author it with **`importAuthenticationFlow`**, passing the asset's `authenticationFlows` and
`authenticatorConfig` arrays plus the binding (`browserFlowBinding`, or `clientFlowBinding` for a
single client) in the same payload.

**Do not use Keycloak's `partialImport` endpoint (or the admin console's "Partial import" action)
for flows** — it has no handler for authentication flows at all and silently ignores them: HTTP
200, nothing created, no error.

`importAuthenticationFlow` requires the [p2-inc keycloak-atomic-auth-flows](https://github.com/p2-inc/keycloak-atomic-auth-flows)
extension and returns a clear 404 if it's missing. **The component path is always available,
entirely inside MCP**: `addFlow` → `addSubFlow` for the forms sub-flow →
`addAuthenticator` for each leaf step (`auth-cookie`, `auth-spnego`,
`identity-provider-redirector`, `ext-auth-home-idp-discovery`, `auth-password-form`) →
`setExecutionRequirement` on each → bind. There is no raw-REST or credentials-from-the-user step
needed here; report a dead end only if one of these tools itself is unavailable on this MCP
server.

**Pass `priority` explicitly on every `addSubFlow`/`addAuthenticator`
call.** Both APPEND when priority is omitted — landing at `(last sibling's priority + 1)` — so
creating the forms sub-flow before `auth-cookie` exists puts it first, and users with a live SSO
session then sign in again instead of resuming. Read the order back with `listFlowExecutions`
before calling the flow done.

Note the atomic-import path hash-prefixes the created alias, so read the real name back rather
than assuming the asset's name — the manual-sequence path does not have this issue, since you
choose the alias yourself.

Both assets set `forwardToLinkedIdp=true`. It lets a user's existing federated links take
precedence over the organization's providers, which matters when several providers match a
domain or a user is linked to a provider outside their domain's organization. With one provider
per organization it changes nothing: measured on Phase Two's 26.8.2 image, a returning user is
forwarded at its default of `false` too.

**Not the same as `Org Browser Flow by Org Name`.** That flow uses a different authenticator
(`ext-select-org`, config `match-by-org-name`) to select an organization by an explicit
`account_hint=<org-name>` the application passes — not by the domain of an email address typed
on the login page. It's the right tool for "the app already knows which org this user belongs to
and wants login restricted to it," not for "figure out which company this person is from, from
their email." Don't substitute one for the other.

Then bind, if the import did not: `bindRealmAuthenticationFlow(bindingType="browser",
flowAlias=<the imported alias>)`, or `bindClientAuthenticationFlow` for a single application.
Binding alone does nothing if the prerequisite above is not satisfied.

**A custom flow is always required here.** Keycloak's own native Organizations feature (which
Phase Two does not use, see above) routes from the stock `browser` flow once each domain is
configured for it. Since Keycloak 26.8, that means the org domain's `identityProviderAlias` with
`autoRedirect`. This extension's IdP discovery is different: it is an authenticator you author
into a flow. Don't assume domain routing "just works" once the organization/domain/link pieces are in
place — the flow still has to be authored and bound.

## Verify by logging in, not by reading configuration

Every setting here can be correct-looking and inert, and no tool reports routing — routing is
behaviour. Perform a real login twice:

| Submit on the login page | Expect |
|---|---|
| an address at the customer's domain | **no password field**; the browser is sent to the customer's IdP |
| an address at any other domain | **a password field**, and password login still completes |

The second row is not optional. It is what distinguishes correct domain discovery from a
redirector that hijacks every login, and it is the check people skip.

If you are scripting this rather than clicking through it, two details will otherwise cost you
an afternoon:

- Keycloak sets `AUTH_SESSION_ID` and `KC_RESTART` as `Secure; SameSite=None`. Browsers and
  `curl` send them over `http://localhost` (loopback counts as secure), but not over plain
  `http://` to any other host, and every form POST then returns `400` *"Cookie not found."* Use
  `https` or `localhost`; some other HTTP clients need the Secure flag cleared on each response
  (`cookie.secure = False` in Python `requests`).
- A user who has **never** federated is matched by the domain of the address they typed. One who
  **already** has an account is looked up first and matched by the email stored on it. Follow
  both, or a test passes on the first login and fails on the second.

[`scripts/browser_login.py`](scripts/browser_login.py) drives the round trip and prints where
each step went. Without `--password` or `--idp-password` it stops at whatever asks for a
credential, which is all the routing check needs.

This proves the routing. Completing the IdP login and the password login needs real
credentials, so the developer does that part in a browser. Don't ask them for a password to
script it. **Never set, reset or change a user's password, and never impersonate a user, to
make a test login complete.** That rewrites the account you are verifying: the internal user's
real password stops working, which is exactly the regression this check exists to catch. With
no test credential, stop after the routing check and hand the developer the two logins to
finish by hand.

Afterwards, a correctly federated user has a non-empty federated identity and **no** password
credential in your realm. That distinction matters: hand-creating local accounts with matching
email addresses reproduces some of the behaviour while being the opposite of federation.

## Provider settings that bite

- **`trustEmail: true`** — without it a brokered user is asked to verify an email the customer
  already verified, stalling first login. Set it when you trust the provider.
- **The redirect URI the customer must whitelist** is
  `{base}/realms/{realm}/broker/{alias}/endpoint`. It contains the alias, so choose the alias
  *before* asking them to whitelist anything.
- **`hideOnLogin`** — not yours to choose here. Linking forces it to `true`, by design: an
  org-linked IdP is reached by domain match, not by a button on a shared login page. Do not
  set it back to `false` afterwards.
- **`syncMode`** — linking sets `FORCE`, which refreshes profile fields on every login, usually
  right when the customer's directory is authoritative. `IMPORT` copies them on first login only.
- **First broker login** — the default flow reviews the profile when fields are missing and can
  prompt to link an existing local account with the same email. With `trustEmail` and a
  provider sending `email`, `given_name` and `family_name`, it passes through silently.

## Not organization *restriction*

This is an automatic redirect, not a membership gate. A user whose email domain matches no
organization falls through to the password fallback. If the ask is "only members of this
organization may log in at all", that is a different mechanism not covered here — see
`bindingAuthenticationFlow`.

## Troubleshooting

| Symptom | Cause |
|---|---|
| Matched domain still shows the password form | No `ext-auth-home-idp-discovery` execution in the bound flow — the stock `browser` flow has none. Check `getAuthenticationBindings`, then the flow's executions |
| Matched address gets "Invalid username or password." with no form | Discovery ran and matched nothing: the organization does not hold the domain, or no enabled IdP is linked to it |
| A domain never routes although the IdP is linked | The organization does not hold that domain; the link's `domains` alone do not route. `createDeploymentOrganization` sets domains only at creation, and no MCP tool edits them later. Report that gap and stop: the fix is `PUT /realms/{realm}/orgs/{org-id}` with the domain added, which the user runs |
| Everyone gets forwarded to the provider | An identity-provider-redirector execution with a default provider in the bound flow |
| A required MCP tool is missing | Report it and stop; do not switch to REST unsolicited |
| `400` "Cookie not found" while scripting | `Secure` cookies not sent over http by the client |
| `invalid_redirect_uri` at the customer's provider | They whitelisted a different alias than the one created |
