---
name: keycloak
description: >-
  Use when doing Keycloak / Phase Two hosted Keycloak admin work. Passwordless login (magic link, email
  OTP, passkey WebAuthn, or passkey-or-magic-link "0 password required"); email OTP as a 2FA second
  factor; org-membership login restriction (password, federated, or magic-link); cluster/deployment
  provisioning; enrolling a credential (passkey/TOTP) onto users who already exist — and refusing
  cluster/deployment/realm DELETION. Also identity brokering: domain-routed corporate SSO;
  social login buttons (Google/GitHub/Microsoft); enterprise IdP federation — Entra ID,
  Okta, Auth0, ADFS, AWS SSO, PingOne, Salesforce and other OIDC/SAML IdPs; and IdP-initiated
  SSO tiles. Triggers: "2FA by email", "passkeys",
  "restrict login to org X", "spin up a cluster", "delete a cluster/realm",
  "set up my passkey", "enroll users in 2FA",
  "connect Okta/Entra ID", "SAML/OIDC SSO".
  Not WebAuthn/TOTP as a second factor, not LDAP/AD user federation, not app-side login
  code — that's `securing-apps`.
license: CC-BY-SA-4.0
metadata:
  version: '0.17.0'
  author: Phase Two <support@phasetwo.io>
---

<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# Keycloak

Detect intent → detect tooling → load 1 reference file. If nothing matches, offer to file a gap
issue instead of guessing (see Step 1's "No intent matches").

This skill is a **router**. It contains no implementation or configuration steps itself — every
instruction lives behind a `Read:` in **Step 3**. Keep this file loaded; load references on demand.

---

## Step 0: Never delete a cluster, deployment, or realm

Read before routing, because this request can arrive dressed as any intent ("tear down the staging
realm", "remove that cluster", "clean up the deployment I made").

**Deny it.** Deleting a Phase Two cluster, deployment, or realm is blocked over MCP for every
caller: `deleteCluster` refuses every call and never reaches the API, and no tool deletes a
deployment or a realm at all. It is irreversible — a deployment *is* a realm, so it takes every
user, client, and flow in it, and every application authenticating against it stops working.

Say plainly that this is console-only and why, point the user at `https://dash.phasetwo.io/clusters`
(or support@phasetwo.io), and stop. Do **not** substitute the Phase Two API, the Keycloak Admin REST
API, `curl`, or another tool; do **not** treat it as a router gap under "No intent matches"; and
never report a deletion as done.

---

## Step 1: Detect intent

| What the developer wants (plain language) | Intent |
|---|---|
| Turn on passwordless login by emailed link — "passwordless login", "log in with a magic link", "email people a login link instead of a password", "let users sign in without a password" (even just "passwordless" alone). Not WebAuthn/passkey passwordless (a different mechanism, see below) and not a one-time code typed in (a sibling authenticator, not covered here). Not restricted to any organization's members — if it should be, see the next row. | **admin:passwordless-magic-link** |
| Passwordless login by a one-time CODE emailed to the user — "email OTP", "email a one-time code", "6-digit code to their email", "login code by email", "OTP by email instead of an authenticator app". The code-you-type sibling of magic-link's link-you-click: same extension, different authenticator (`ext-email-otp`), and unlike magic-link **no built-in flow exists** so one must be authored. Not Keycloak's TOTP/HOTP (an authenticator app needing device enrollment) and not magic link (row above). | **admin:email-otp-login** |
| Password login, hardened with an emailed one-time code as a SECOND factor — "email OTP as MFA", "password plus a code emailed to me", "2FA by email", "require a login code after the password", "email-based two-factor". NOT passwordless — the password is still required and gates the OTP (a wrong password never even sends the email). Uses the same `ext-email-otp` authenticator as the row above but a different, load-bearing first step (`auth-username-password-form`, not an identifier-only step). Not the passwordless row above, and not WebAuthn/TOTP as a second factor. | **admin:password-email-otp-mfa** |
| Magic-link login, but only for members of a specific organization — "magic link restricted to org X", "passwordless login gated by organization membership", "only email the link to people on this team", "a user logs in with magic link and account_hint decides if they get in". This is the combination of the row above with the account_hint-gated org check `admin:org-restrict-login` uses for password logins — neither the plain `magic link` flow nor `Org Browser Flow` alone covers this; it needs a custom flow that runs the org check *before* the email goes out. Needs the keycloak-orgs extension, same as the org-restrict rows below. | **admin:passwordless-magic-link-org-restrict** |
| Turn on passkey-only login — "passkey login", "no more passwords", "sign in with a passkey/security key/Face ID/Touch ID and nothing else", "remove password login entirely in favor of WebAuthn" (even just "passkeys" alone). Not WebAuthn as a second factor alongside a password (a different, simpler policy, not covered here) and not magic-link's email mechanism (no cryptographic ceremony involved). | **admin:passwordless-passkey** |
| One login flow offering a passkey **OR** a magic link, with no password anywhere — "0 password required login", "zero password login", "passkeys or magic link", "let them use a passkey or email them a link", "passwordless with a fallback that isn't a password". Branded the "0 password required login flow". The two methods sit side by side as alternatives, which is also how a brand-new user with no passkey gets in at all (magic link *is* the passkey bootstrap path). Not passkey-only (`admin:passwordless-passkey`) and not magic-link-only (`admin:passwordless-magic-link`) — pick this only when **both** methods are wanted in one flow. | **admin:zero-password-login** |
| Get a credential onto a user who ALREADY exists — "set up my passkey", "enroll users in TOTP/2FA", "how does a user get their first passkey", "force a password reset". Two variants, chosen by prerequisite rather than preference: a required action on the user (they must already be able to log in; no SMTP) or an emailed enrollment link (needs SMTP; works with no credential at all). The step that makes a passwordless flow usable — authoring/binding that flow is the rows above, not this one. | **admin:credential-enrollment** |
| Provision a new dedicated Phase Two hosted Keycloak cluster — "spin up a cluster", "set up hosted Keycloak", "I need a new Phase Two instance", "get a managed Keycloak running". | **admin:cluster-setup** |
| Create a new deployment (realm) in an existing cluster — "add a deployment", "new realm in my cluster", or phrased indirectly: "I want to secure/isolate this app", "give this app its own tenant/bounded security context", "separate environment for staging vs production". Not cluster provisioning itself (that's `admin:cluster-setup`, use it first if no cluster exists) and not realm-level settings on a deployment that already exists (not covered by this skill). | **admin:cluster-create-deployment** |
| Route a user to their own company's identity provider based on their email domain, while everyone else keeps password login — "corporate SSO", "enterprise SSO", "let our customer log in with their company account", "redirect to my corporate IdP", "home realm discovery", "IdP discovery by email domain". Not a plain IdP button shown to everyone with no domain routing (that's `admin:idp-federation`, next row) and not restricting login to organization members (a different mechanism — see the two rows after that). | **admin:corporate-sso** |
| Add a built-in **consumer social login** button — "log in with Google", "add a GitHub login button", "sign in with Microsoft/Facebook", "social login", "OAuth login with \[Google/GitHub/Microsoft/Facebook/...\]". Client ID + secret only, no discovery/metadata URL. Not a company's own Workspace/Entra ID/Okta tenant (that's enterprise federation, next row — "Google" as a company SSO source means Google **Workspace SAML**, not this) and not domain-routed (`admin:corporate-sso` above). | **admin:social-login** |
| Broker a company's own enterprise identity provider as a login option — "connect Okta/Entra ID/Auth0/ADFS/PingOne/...", "set up SAML SSO with \[vendor\]", "add \[vendor\] as an identity provider", "OIDC/SAML federation with our IdP" — Entra ID, Auth0, ADFS, AWS SSO, Google Workspace, CyberArk, JumpCloud, OneLogin, Oracle, PingOne, Duo, Salesforce, LastPass, Cloudflare Access, Okta, or any other generic OIDC/SAML 2.0 IdP. Not domain-auto-routing (`admin:corporate-sso` — this intent creates the button, that one decides who gets redirected automatically), not a consumer social button (`admin:social-login` above), and not LDAP/AD user federation — that's a directory read via `createLdapUserStorage`, an uncovered intent in this router, not a missing tool. | **admin:idp-federation** |
| Start login from an external portal **tile** so a user lands in ONE specific app already logged in — "Okta dashboard tile into my app", "Entra ID / My Apps tile", "IdP-initiated SSO", "unsolicited SAML login", "start login from Okta/Entra instead of the app". Advanced and opt-in: the tile targets a single client, chosen by a `{urlName}` path segment on the client (NOT by RelayState, which Keycloak discards on this path). Requires that vendor to already be brokered as a SAML IdP. Not plain "log in with Okta/Entra" (`admin:idp-federation` — one button, every client, app-initiated) and not domain routing (`admin:corporate-sso`). | **admin:idp-initiated-sso** |
| Restrict login so only members of a specific organization can complete it — "only let members of this org log in", "gate login by organization membership", "restrict access to org X". Not domain-based auto-routing (that's `admin:corporate-sso` — a user can be routed to an IdP without any membership restriction at all) and not a login that "just works" once bound — it only activates when the request carries `account_hint` or `prompt=select_account`. This row is for **local password** logins; if the user authenticates at an external IdP, see the next row. | **admin:org-restrict-login** |
| Restrict **federated/SSO** login so only members of a specific organization get in — "corporate organization restriction", "restrict SSO login to a team/tenant", "only let this customer's staff into their own org", "organization-restricted corporate login", "gate IdP login by org membership", "post-broker organization check". The user signs in at an external identity provider and the membership check runs *afterwards*, bound to the IdP's post-broker login flow. Not domain-based routing (`admin:corporate-sso` sends users to their IdP but restricts nobody) and not the local-password gate (`admin:org-restrict-login`). | **admin:idp-org-restrict-login** |

### No intent matches

Don't force an uncovered request into `admin:passwordless-magic-link` — that produces confidently
wrong guidance. If the request is genuinely something else
(plugin development, realm/client administration, IdP federation, or anything not in the table
above):

0. If the request is to **delete** a cluster, deployment, or realm, Step 0 already answers it —
   deny it and don't file anything.
1. Say plainly that this isn't covered yet, and what you understood the request to be.
2. Ask if they'd like an issue opened in this repo (`p2-inc/keycloak-skills`) describing the gap —
   that's how this router grows new intents instead of silently mis-routing.
3. If they say yes, draft the issue with:
   - **The verbatim prompt** — the developer's own request text, unedited, in a quoted block; a
     paraphrase loses exactly the phrasing future router updates need. Never summarize it away.
   - Which intent(s) it was checked against and why nothing matched.
   - Anything else relevant already established in this conversation.

   Show the drafted issue before filing — it's a public action and needs their explicit go-ahead
   on the actual content, not just the idea of filing.
4. If they decline, or there's no way to open an issue (no `gh`/git remote), leave it — don't
   paper over the gap by answering anyway.

The same offer applies when a **covered** intent's reference file itself fails — steps error out
or prove wrong. That issue names the file and what went wrong alongside the verbatim prompt; keep
helping the developer either way.

---

## Step 2: Are you a Phase Two user?

This one question decides the **tooling** — ask it directly rather than trying to infer it from
context. Don't ask twice in the same conversation once it's established.

| Answer | Tooling |
|---|---|
| **Yes — Phase Two hosted Keycloak.** | **mcp.** The `phasetwo` plugin declares this server, so it should already be there as `keycloak` (`https://mcp.phasetwo.io/mcp`). If its tools aren't available, that is usually an unauthorized OAuth connection rather than a missing server — have the developer check `/mcp`; outside the plugin, `claude mcp add --transport http keycloak https://mcp.phasetwo.io/mcp`. If they decline, say plainly that `rest` is not a substitute here: a Phase Two hosted deployment has no self-service admin REST credential of any kind, so the `rest` files fail at their very first step — there is nothing to put in `$ADMIN_TOKEN`. Point them at reconnecting MCP or the dashboard. |
| **No — self-managed Keycloak** (bare metal, Docker, Kubernetes; the developer has direct Admin REST access). | **rest.** |

If the answer is ambiguous, ask — don't guess and don't default to either side.

### On tooling=mcp: verify the tools once, before Step 3

Check the tool list for the specific tools the chosen intent needs (each reference file names
them). Do it **once, up front** — never by calling a tool to see whether it exists, and never
discovering the gap one step at a time. Trickling into a fallback mid-task is measurably worse
than deciding at the start: in one measured run it cost 39% more tool calls and 51% more prompt
tokens than committing to a path immediately.

If tools are missing, say which, and diagnose before retrying:

- **No `keycloak` tools at all** → the OAuth connection is unauthorized. Have the developer
  check `/mcp`.
- **Some tools present, later-alphabet ones missing** (`setSmtpSettings`, `updateRealm`, and
  similar) → the client is showing only the first page of `tools/list`. MCP paginates, and a
  client that ignores `nextCursor` sees one page — Codex does this
  ([openai/codex#28858](https://github.com/openai/codex/issues/28858)). It is not a permissions
  or scope problem, and re-authenticating will not fix it. Either raise the server's page size
  above its tool count, or do this work in a client that pages.

Do **not** silently substitute `rest` on a Phase Two hosted deployment — there is no admin
credential there, so the `rest` files fail at their first step. Stop and fix the connection.

---

## Step 3: Load reference files

For intent `admin:X`, read `references/admin-X-{tooling}.md`:

```
tooling=mcp  → references/admin-X-mcp.md
tooling=rest → references/admin-X.md   (no suffix)
```

Each reference file carries its own prerequisites (required p2-inc extension jars), flow-shape
and execution-order rules, per-vendor sub-file mappings under `references/idp/`, and any step
that has no tool on one tooling — follow the file, don't answer from this router. The full
per-intent file inventory is indexed in [`references/README.md`](references/README.md).

Two exceptions, **mcp-only**: `admin:cluster-setup` → `references/cluster-setup-mcp.md` and
`admin:cluster-create-deployment` → `references/cluster-create-deployment-mcp.md`. On
tooling=rest, say plainly that cluster provisioning is a Phase Two control-plane capability with
no self-managed equivalent — don't offer a REST workaround; the capability doesn't exist there.

Authoring or editing a flow (any intent whose reference file creates, binds, or reorders
authentication executions)? Also read
[`references/flow-execution-order.md`](references/flow-execution-order.md) — shared across those
intents. It carries the **shape** rule (every level all-ALTERNATIVE or all-REQUIRED/CONDITIONAL;
mixing them makes Keycloak silently erase the alternatives) and the **order** rule (the create
calls do not establish order — read it back and repair). Both fail without an error.
