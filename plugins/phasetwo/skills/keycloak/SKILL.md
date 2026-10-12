---
name: keycloak
description: >-
  Use when doing Keycloak / Phase Two hosted Keycloak admin work. Login methods: magic link, email
  OTP, passkeys (WebAuthn), TOTP 2FA, password-or-passkey, "0 password required", step-up /
  re-authentication (LoA, ACR). Org-membership login restriction. Enrolling or resetting
  passkeys/TOTP for existing users, incl. lost-device links. Cluster/deployment provisioning (a new deployment or
  realm in an existing cluster), and refusing DELETION: delete, remove, tear down a cluster, deployment or realm. Identity brokering:
  domain-routed corporate SSO; social login (Google/GitHub/Microsoft); enterprise IdPs (Entra ID,
  Okta, Auth0, ADFS, AWS SSO, PingOne, Salesforce, OIDC/SAML); IdP-initiated SSO tiles. Triggers:
  "2FA by email", "passkeys", "ask for a code again on the payments page", "restrict login to
  org X", "spin up a cluster", "tear down the realm", "connect Okta/Entra ID". Not LDAP/AD user
  federation, not app-side login code — that's `securing-apps`.
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
| Passwordless login by an emailed **link** — "passwordless login", "log in with a magic link", "email people a login link instead of a password", "let users sign in without a password" (even just "passwordless"). Not passkeys (`admin:passwordless-passkey`), not a typed code (`admin:email-otp-login`), not limited to an organization (`admin:passwordless-magic-link-org-restrict`). | **admin:passwordless-magic-link** |
| Passwordless login by a one-time **code** emailed to the user — "email OTP", "email a one-time code", "6-digit code to their email", "login code by email". Not an authenticator app (`admin:totp-second-factor`), not a link (`admin:passwordless-magic-link`), not a code after the password (`admin:password-email-otp-mfa`). | **admin:email-otp-login** |
| Password, then an emailed one-time code as a SECOND factor — "email OTP as MFA", "2FA by email", "password plus a code emailed to me", "require a login code after the password", "email-based two-factor". Not passwordless (`admin:email-otp-login`), not an authenticator-app code (`admin:totp-second-factor`), not WebAuthn as a second factor. | **admin:password-email-otp-mfa** |
| Password, then a TOTP code from an authenticator app as a SECOND factor — "TOTP as 2FA", "authenticator app as second factor", "Google Authenticator/Authy code after the password", "require a TOTP code after the password". Not an emailed code (`admin:password-email-otp-mfa`), not enrolling existing users (`admin:credential-enrollment`). | **admin:totp-second-factor** |
| Magic-link login only for members of one organization — "magic link restricted to org X", "passwordless login gated by organization membership", "only email the link to this team", "account_hint decides who gets the link". Not plain magic link (`admin:passwordless-magic-link`), not the password-login org gate (`admin:org-restrict-login`). | **admin:passwordless-magic-link-org-restrict** |
| Passkey-only login — "passkey login", "no more passwords", "sign in with a passkey/security key/Face ID/Touch ID and nothing else", "remove password login entirely in favor of WebAuthn" (even just "passkeys"). Not a passkey as a second factor after a password, not password-or-passkey (`admin:password-or-passkey-login`), not passkey-or-magic-link (`admin:zero-password-login`). | **admin:passwordless-passkey** |
| A passkey **OR** a magic link, no password anywhere — "0 password required login", "zero password login", "passkeys or magic link", "passwordless with a fallback that isn't a password". Only when **both** methods are wanted: not passkey-only (`admin:passwordless-passkey`), not magic-link-only (`admin:passwordless-magic-link`). | **admin:zero-password-login** |
| Username/password **OR** a passkey as alternative first factors — "username and password with passkeys option", "password or passkey login", "keep passwords but add passkeys". Not zero-password (`admin:zero-password-login`), not passkey-only (`admin:passwordless-passkey`). | **admin:password-or-passkey-login** |
| Get a credential onto a user who ALREADY exists — "set up my passkey", "enroll users in TOTP/2FA", "how does a user get their first passkey", "force a password reset". Not authoring or binding a login flow (the rows above). | **admin:credential-enrollment** |
| Provision a new dedicated Phase Two hosted Keycloak cluster — "spin up a cluster", "set up hosted Keycloak", "I need a new Phase Two instance", "get a managed Keycloak running". | **admin:cluster-setup** |
| Create a new deployment (realm) in an existing cluster — "add a deployment", "new realm in my cluster", "I want to secure/isolate this app", "give this app its own tenant/bounded security context", "separate staging and production". Not provisioning the cluster (`admin:cluster-setup` first, if none exists), not settings on an existing realm (not covered). | **admin:cluster-create-deployment** |
| Send users to their own company's IdP by email domain; everyone else keeps password login — "corporate SSO", "enterprise SSO", "log in with their company account", "redirect to my corporate IdP", "home realm discovery", "IdP discovery by email domain". Not one IdP button for everyone (`admin:idp-federation`), not an organization gate (`admin:org-restrict-login`, `admin:idp-org-restrict-login`). | **admin:corporate-sso** |
| A consumer **social login** button — "log in with Google", "add a GitHub login button", "sign in with Microsoft/Facebook", "social login". Not a company's own Workspace/Entra ID/Okta tenant (`admin:idp-federation`; "Google" as company SSO means Google **Workspace SAML**), not domain routing (`admin:corporate-sso`). | **admin:social-login** |
| Broker a company's own enterprise IdP as a login option — "connect Okta/Entra ID/Auth0/ADFS/PingOne", "SAML SSO with \[vendor\]", "add \[vendor\] as an identity provider", "OIDC/SAML federation with our IdP"; Entra ID, Okta, Auth0, ADFS, AWS SSO, Google Workspace, PingOne, OneLogin, JumpCloud, CyberArk, Duo, Oracle, Salesforce, LastPass, Cloudflare Access, or any OIDC/SAML 2.0 IdP. Not domain routing (`admin:corporate-sso`), not a consumer button (`admin:social-login`), not LDAP/AD user federation (not covered by an intent, though `createLdapUserStorage` exists). | **admin:idp-federation** |
| Login started from an external portal **tile** into ONE app — "Okta dashboard tile into my app", "Entra ID / My Apps tile", "IdP-initiated SSO", "unsolicited SAML login", "start login from Okta/Entra instead of the app". Needs the vendor already brokered as a SAML IdP. Not plain "log in with Okta/Entra" (`admin:idp-federation`), not domain routing (`admin:corporate-sso`). | **admin:idp-initiated-sso** |
| Only members of a specific organization may complete a **local password** login — "only let members of this org log in", "gate login by organization membership", "restrict access to org X". Not domain routing (`admin:corporate-sso`), not federated/SSO logins (`admin:idp-org-restrict-login`). | **admin:org-restrict-login** |
| Only members of a specific organization may complete a **federated/SSO** login — "corporate organization restriction", "restrict SSO login to a team/tenant", "only let this customer's staff into their own org", "gate IdP login by org membership", "post-broker organization check". Not domain routing (`admin:corporate-sso`), not the local-password gate (`admin:org-restrict-login`). | **admin:idp-org-restrict-login** |

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
