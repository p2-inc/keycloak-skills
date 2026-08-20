---
name: keycloak
description: >-
  Use when doing Keycloak/Phase Two hosted Keycloak admin work: passwordless login (magic link or
  passkey-only WebAuthn), corporate/enterprise SSO by email domain, and Phase Two cluster/
  deployment provisioning — including "isolate/secure this app" meaning "new deployment".
  Triggers: "passwordless login", "magic link", "passkey login", "no more passwords", "corporate
  SSO", "enterprise SSO", "home realm discovery", "spin up a cluster", "new deployment",
  "isolate/secure this app" — even bare "passwordless"/"passkeys". Magic-link, passkey, corporate
  SSO: raw Admin REST or Keycloak MCP server. Cluster/deployment: Keycloak-MCP-only. Also
  restricting login to one organization's members — either for local password logins or for
  federated/SSO logins through an external IdP ("corporate organization restriction",
  post-broker org check); both account_hint-gated, either tooling, need the keycloak-orgs
  extension. Also magic-link login itself restricted to one organization's members — "magic
  link but only for members of org X", "passwordless login gated by organization", "only send
  the login link to people in this team" — a custom flow combining the magic-link authenticator
  with the same account_hint-gated org check, distinct from plain magic-link (no restriction)
  and from the password-only org gate above. Not WebAuthn as a second factor, one-time-code
  login, or general administration.
license: Apache-2.0
metadata:
  version: '0.11.0'
  author: Phase Two <support@phasetwo.io>
---

# Keycloak

Detect intent → detect tooling → load 1 reference file. If nothing matches, offer to file a gap
issue instead of guessing (see Step 1's "No intent matches").

This skill is a **router**. It contains no implementation or configuration steps itself — every
instruction lives behind a `Read:` in **Step 3**. Keep this file loaded; load references on demand.

---

## Step 1: Detect intent

| What the developer wants (plain language) | Intent |
|---|---|
| Turn on passwordless login by emailed link — "passwordless login", "log in with a magic link", "email people a login link instead of a password", "let users sign in without a password" (even just "passwordless" alone). Not WebAuthn/passkey passwordless (a different mechanism, see below) and not a one-time code typed in (a sibling authenticator, not covered here). Not restricted to any organization's members — if it should be, see the next row. | **admin:passwordless-magic-link** |
| Magic-link login, but only for members of a specific organization — "magic link restricted to org X", "passwordless login gated by organization membership", "only email the link to people on this team", "a user logs in with magic link and account_hint decides if they get in". This is the combination of the row above with the account_hint-gated org check `admin:org-restrict-login` uses for password logins — neither the plain `magic link` flow nor `Org Browser Flow` alone covers this; it needs a custom flow that runs the org check *before* the email goes out. Needs the keycloak-orgs extension, same as the org-restrict rows below. | **admin:passwordless-magic-link-org-restrict** |
| Turn on passkey-only login — "passkey login", "no more passwords", "sign in with a passkey/security key/Face ID/Touch ID and nothing else", "remove password login entirely in favor of WebAuthn" (even just "passkeys" alone). Not WebAuthn as a second factor alongside a password (a different, simpler policy, not covered here) and not magic-link's email mechanism (no cryptographic ceremony involved). | **admin:passwordless-passkey** |
| Provision a new dedicated Phase Two hosted Keycloak cluster — "spin up a cluster", "set up hosted Keycloak", "I need a new Phase Two instance", "get a managed Keycloak running". | **admin:cluster-setup** |
| Create a new deployment (realm) in an existing cluster — "add a deployment", "new realm in my cluster", or phrased indirectly: "I want to secure/isolate this app", "give this app its own tenant/bounded security context", "separate environment for staging vs production". Not cluster provisioning itself (that's `admin:cluster-setup`, use it first if no cluster exists) and not realm-level settings on a deployment that already exists (not covered by this skill). | **admin:cluster-create-deployment** |
| Route a user to their own company's identity provider based on their email domain, while everyone else keeps password login — "corporate SSO", "enterprise SSO", "let our customer log in with their company account", "redirect to my corporate IdP", "home realm discovery", "IdP discovery by email domain". Not a plain IdP button shown to everyone (that's identity brokering generally, not domain-routed — not covered here) and not restricting login to organization members (a different mechanism — see the next two rows). | **admin:corporate-sso** |
| Restrict login so only members of a specific organization can complete it — "only let members of this org log in", "gate login by organization membership", "restrict access to org X". Not domain-based auto-routing (that's `admin:corporate-sso` — a user can be routed to an IdP without any membership restriction at all) and not a login that "just works" once bound — it only activates when the request carries `account_hint` or `prompt=select_account`. This row is for **local password** logins; if the user authenticates at an external IdP, see the next row. | **admin:org-restrict-login** |
| Restrict **federated/SSO** login so only members of a specific organization get in — "corporate organization restriction", "restrict SSO login to a team/tenant", "only let this customer's staff into their own org", "organization-restricted corporate login", "gate IdP login by org membership", "post-broker organization check". The user signs in at an external identity provider and the membership check runs *afterwards*, bound to the IdP's post-broker login flow. Not domain-based routing (`admin:corporate-sso` sends users to their IdP but restricts nobody) and not the local-password gate (`admin:org-restrict-login`). | **admin:idp-org-restrict-login** |

### No intent matches

Don't force an uncovered request into `admin:passwordless-magic-link` just to have somewhere to
send it — that produces confidently wrong guidance. If the request is genuinely something else
(plugin development, realm/client administration, IdP federation, or anything not in the table
above):

1. Say plainly that this isn't covered yet, and what you understood the request to be.
2. Ask if they'd like an issue opened in this repo (`p2-inc/agent-skills`) describing the gap —
   that's how this router grows new intents (see `references/README.md`'s "growing this router"
   note) instead of silently mis-routing.
3. If they say yes, draft the issue with:
   - **The verbatim prompt** — the developer's own request text, unedited, in a quoted block. This
     is the point of filing the issue at all: a paraphrase loses exactly the phrasing future router
     updates need to recognize this case. Never summarize it away.
   - Which intent(s) it was checked against and why nothing matched.
   - Anything else relevant already established in this conversation.

   Show the drafted issue to them before filing anything — opening an issue is a public, visible
   action and needs their explicit go-ahead on the actual content, not just on the idea of filing one.
4. If they decline, or if there's no way to open an issue (no `gh`/git remote access), just leave it
   there — don't paper over the gap by answering anyway.

---

## Step 2: Are you a Phase Two user?

This one question decides the **tooling** — ask it directly rather than trying to infer it from
context. Don't ask twice in the same conversation once it's established.

| Answer | Tooling |
|---|---|
| **Yes — Phase Two hosted Keycloak.** | **mcp.** If the `keycloak` MCP server isn't connected yet, prompt for it now: `mcp add --transport http keycloak https://mcp-staging.phasetwo.io/mcp`. If the developer declines, fall back to `rest` and say upfront what can't be verified as a result. |
| **No — self-managed Keycloak** (bare metal, Docker, Kubernetes; the developer has direct Admin REST access). | **rest.** |

If the answer is ambiguous, ask — don't guess and don't default to either side.

---

## Step 3: Load reference files

### admin:passwordless-magic-link
```
Read: references/admin-passwordless-magic-link-{tooling}.md
  tooling=mcp  → references/admin-passwordless-magic-link-mcp.md
  tooling=rest → references/admin-passwordless-magic-link.md
```

### admin:passwordless-magic-link-org-restrict
```
Read: references/admin-passwordless-magic-link-org-restrict-{tooling}.md
  tooling=mcp  → references/admin-passwordless-magic-link-org-restrict-mcp.md
  tooling=rest → references/admin-passwordless-magic-link-org-restrict.md
```
Requires the p2-inc `keycloak-orgs` extension, same as `admin:org-restrict-login` below. The
custom flow's execution order is load-bearing: the org check has to run *before* the magic-link
send step, or a non-member would still receive the email. Don't drop to plain
`admin:passwordless-magic-link` guidance just because the request mentions "magic link" — check
for an organization-restriction requirement first.

### admin:passwordless-passkey
```
Read: references/admin-passwordless-passkey-{tooling}.md
  tooling=mcp  → references/admin-passwordless-passkey-mcp.md
  tooling=rest → references/admin-passwordless-passkey.md
```

### admin:cluster-setup
```
Read: references/cluster-setup-mcp.md   (tooling=mcp only)
```
If tooling=rest (self-managed Keycloak), say plainly that cluster provisioning is a Phase Two
SaaS control-plane capability with no self-managed equivalent — there is no cluster/deployment
concept to provision outside Phase Two's hosted platform. Don't offer a REST workaround; this
isn't a missing reference doc, it's a capability that doesn't exist for that tooling.

### admin:cluster-create-deployment
```
Read: references/cluster-create-deployment-mcp.md   (tooling=mcp only)
```
Same tooling=rest handling as `admin:cluster-setup` immediately above — say plainly this doesn't
apply to self-managed Keycloak, don't improvise a REST equivalent.

### admin:corporate-sso
```
Read: references/admin-corporate-sso-{tooling}.md
  tooling=mcp  → references/admin-corporate-sso-mcp.md
  tooling=rest → references/admin-corporate-sso.md
```

### admin:idp-org-restrict-login
```
Read: references/admin-idp-org-restrict-login-{tooling}.md
  tooling=mcp  → references/admin-idp-org-restrict-login-mcp.md
  tooling=rest → references/admin-idp-org-restrict-login.md
```
Both paths require the p2-inc `keycloak-orgs` extension. Note this binds to the identity
provider's **post-broker login flow** — a different surface from the realm/client browser flow
the other org intent uses; Keycloak's stock post-broker flow contains no `ext-select-org`, so
binding that one gates nothing.

### admin:org-restrict-login
```
Read: references/admin-org-restrict-login-{tooling}.md
  tooling=mcp  → references/admin-org-restrict-login-mcp.md
  tooling=rest → references/admin-org-restrict-login.md
```
Both paths require the p2-inc `keycloak-orgs` extension on the target Keycloak — the reference
files say so up front, because nothing in this intent works without it.
