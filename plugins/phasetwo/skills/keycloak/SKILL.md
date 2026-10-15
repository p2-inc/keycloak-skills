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
| Passwordless login by emailed link — "passwordless login", "magic link", "email a login link instead of a password" (even "passwordless" alone). Not WebAuthn/passkey, not a typed code. Not org-restricted — see below if it should be. | **admin:passwordless-magic-link** |
| Passwordless login by a one-time CODE emailed to the user — "email OTP", "6-digit code to their email", "login code by email". The code-you-type sibling of magic-link: same extension, different authenticator (`ext-email-otp`), and **no built-in flow exists** so one must be authored. Not TOTP/HOTP (an app, device enrollment) and not magic link. | **admin:email-otp-login** |
| Password login hardened with an emailed one-time code as a SECOND factor — "email OTP as MFA", "2FA by email", "code emailed after the password". NOT passwordless — a wrong password never sends the email. Same `ext-email-otp` authenticator as above but gated by `auth-username-password-form` first. Not passwordless, not WebAuthn/TOTP MFA. | **admin:password-email-otp-mfa** |
| Password login hardened with a TOTP app code as a SECOND factor — "TOTP as 2FA", "authenticator app second factor", "code from Google Authenticator/Authy after the password". NOT passwordless — a wrong password never reaches the TOTP step. Uses stock `auth-otp-form`. Not email-OTP MFA, not credential enrollment (which only gets TOTP onto users). | **admin:totp-second-factor** |
| Magic-link login restricted to one organization's members — "magic link restricted to org X", "passwordless gated by org membership". Combines magic-link with the account_hint-gated org check `admin:org-restrict-login` uses; needs a custom flow running the org check before the email sends, and the keycloak-orgs extension. | **admin:passwordless-magic-link-org-restrict** |
| Passkey-only login — "passkey login", "no more passwords", "sign in with passkey/Face ID/Touch ID only". Not WebAuthn as a second factor alongside a password, not magic-link. | **admin:passwordless-passkey** |
| One flow offering passkey **OR** magic link, no password — "0 password required login", "passkeys or magic link". The "0 password required login flow": both sit as alternatives, and magic link is how a brand-new user bootstraps a passkey. Not passkey-only, not magic-link-only — only when **both** are wanted. | **admin:zero-password-login** |
| Username/password **OR** passkey as alternative first factors — "password or passkey login", "keep passwords but add passkey as an alternative". Not zero-password (password still valid), not passkey-only, not magic-link. `auth-username-password-form` + `webauthn-authenticator-passwordless` as ALTERNATIVE siblings, plus realm WebAuthn passwordless policy. | **admin:password-or-passkey-login** |
| Get a credential onto a user who ALREADY exists — "set up my passkey", "enroll users in TOTP/2FA", "force a password reset". Two variants by prerequisite: a required action (user can already log in, no SMTP) or an emailed enrollment link (needs SMTP, no credential needed). Not authoring/binding the flow itself — the rows above. | **admin:credential-enrollment** |
| Provision a new dedicated Phase Two hosted Keycloak cluster — "spin up a cluster", "set up hosted Keycloak". | **admin:cluster-setup** |
| Create a new deployment (realm) in an existing cluster — "add a deployment", "new realm in my cluster", or indirectly "isolate/secure this app", "its own tenant". Not cluster provisioning (`admin:cluster-setup` first) and not settings on an existing deployment. | **admin:cluster-create-deployment** |
| Route a user to their own company's IdP by email domain, everyone else keeps password login — "corporate SSO", "home realm discovery", "IdP discovery by email domain". Not a plain IdP button shown to everyone (`admin:idp-federation`) and not org-membership restriction (the two rows after that). | **admin:corporate-sso** |
| Built-in **consumer social login** button — "log in with Google/GitHub/Microsoft/Facebook", "social login". Client ID + secret only, no metadata URL. Not a company's own tenant (enterprise federation, next row), not domain-routed. | **admin:social-login** |
| Broker a company's own enterprise IdP as a login option — "connect Okta/Entra ID/Auth0/ADFS/PingOne/...", "SAML SSO with \[vendor\]" — Entra ID, Auth0, ADFS, AWS SSO, Google Workspace, CyberArk, JumpCloud, OneLogin, Oracle, PingOne, Duo, Salesforce, LastPass, Cloudflare Access, Okta, or any generic OIDC/SAML 2.0 IdP. Not domain-auto-routing (`admin:corporate-sso` creates this button, that one auto-redirects), not social login, not LDAP/AD (an uncovered intent, not a missing tool). | **admin:idp-federation** |
| External portal **tile** landing a user in ONE app already logged in — "Okta/Entra dashboard tile", "IdP-initiated SSO", "unsolicited SAML login". Opt-in: targets a single client via a `{urlName}` path segment (not RelayState, discarded here). Requires the vendor already brokered as a SAML IdP. Not plain "log in with Okta/Entra" (`admin:idp-federation`), not domain routing. | **admin:idp-initiated-sso** |
| Restrict **local password** login to one organization's members — "only let members of this org log in", "restrict access to org X". Not domain auto-routing, and only activates with `account_hint` or `prompt=select_account`. Federated login: see next row. | **admin:org-restrict-login** |
| Restrict **federated/SSO** login to one organization's members — "restrict SSO login to a team/tenant", "post-broker organization check". The membership check runs after the external IdP login, bound to its post-broker flow. Not domain routing, not the local-password gate above. | **admin:idp-org-restrict-login** |
| Two trust levels in one session, expiring separately — "step-up authentication", "ACR", "LoA", "self-locking session", "MFA only for payments", "step up to gold/silver". Ordinary use needs only a password (level 1); a sensitive action also asks for a one-time code (level 2) — a user who already has level 1 gives only the code. Level 2 expires back to level 1 after a short window with no logout (Janua's "self-locking session"); level 1 lasts the whole SSO session. One client can be pinned to always require level 2. Not the MFA rows above (every login two-factor, no levels, nothing expires back) and not credential enrollment. | **admin:step-up-authentication** |

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
calls do not establish order — read it back and repair). Both fail without an error. This includes
`admin:step-up-authentication`, whose CONDITIONAL level sub-flows are themselves ordered
lowest-level-first.
