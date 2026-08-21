---
name: keycloak
description: >-
  Use when doing Keycloak/Phase Two hosted Keycloak admin work. Passwordless login (magic link, email 
  OTP, passkey WebAuthn, or passkey-or-magic-link "0 password required"); email OTP as a 2FA second
  factor; org-membership login restriction (password, federated, or magic-link); cluster/deployment
  provisioning. Also identity brokering: domain-routed corporate SSO ("route by email domain"); 
  social login buttons ("log in with Google/GitHub/Microsoft/Facebook"); enterprise IdP
  federation — Entra ID, Okta, Auth0, ADFS, AWS SSO, Workspace, PingOne, OneLogin, Oracle, Duo,
  CyberArk, JumpCloud, LastPass, Salesforce, or Cloudflare Access as a login button; and IdP-initiated 
  SSO tiles into one app. Triggers: "passwordless", "magic link", "email OTP", "2FA by email", 
  "passkeys", "0 password required", "restrict login to org X", "spin up a cluster", "corporate SSO", 
  "log in with Google/GitHub", "connect Okta/Entra ID/Auth0", "add an identity provider",
  "SAML/OIDC SSO", "IdP-initiated SSO", "Okta/Entra tile". Cluster/deployment is MCP-only. 
  Not WebAuthn/TOTP as a second factor, not LDAP/AD user federation.
  
license: Apache-2.0
metadata:
  version: '0.14.0'
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
| Passwordless login by a one-time CODE emailed to the user — "email OTP", "email a one-time code", "6-digit code to their email", "login code by email", "OTP by email instead of an authenticator app". The code-you-type sibling of magic-link's link-you-click: same extension, different authenticator (`ext-email-otp`), and unlike magic-link **no built-in flow exists** so one must be authored. Not Keycloak's TOTP/HOTP (an authenticator app needing device enrollment) and not magic link (row above). | **admin:email-otp-login** |
| Password login, hardened with an emailed one-time code as a SECOND factor — "email OTP as MFA", "password plus a code emailed to me", "2FA by email", "require a login code after the password", "email-based two-factor". NOT passwordless — the password is still required and gates the OTP (a wrong password never even sends the email). Uses the same `ext-email-otp` authenticator as the row above but a different, load-bearing first step (`auth-username-password-form`, not an identifier-only step). Not the passwordless row above, and not WebAuthn/TOTP as a second factor. | **admin:password-email-otp-mfa** |
| Magic-link login, but only for members of a specific organization — "magic link restricted to org X", "passwordless login gated by organization membership", "only email the link to people on this team", "a user logs in with magic link and account_hint decides if they get in". This is the combination of the row above with the account_hint-gated org check `admin:org-restrict-login` uses for password logins — neither the plain `magic link` flow nor `Org Browser Flow` alone covers this; it needs a custom flow that runs the org check *before* the email goes out. Needs the keycloak-orgs extension, same as the org-restrict rows below. | **admin:passwordless-magic-link-org-restrict** |
| Turn on passkey-only login — "passkey login", "no more passwords", "sign in with a passkey/security key/Face ID/Touch ID and nothing else", "remove password login entirely in favor of WebAuthn" (even just "passkeys" alone). Not WebAuthn as a second factor alongside a password (a different, simpler policy, not covered here) and not magic-link's email mechanism (no cryptographic ceremony involved). | **admin:passwordless-passkey** |
| One login flow offering a passkey **OR** a magic link, with no password anywhere — "0 password required login", "zero password login", "passkeys or magic link", "let them use a passkey or email them a link", "passwordless with a fallback that isn't a password". Branded the "0 password required login flow". The two methods sit side by side as alternatives, which is also how a brand-new user with no passkey gets in at all (magic link *is* the passkey bootstrap path). Not passkey-only (`admin:passwordless-passkey`) and not magic-link-only (`admin:passwordless-magic-link`) — pick this only when **both** methods are wanted in one flow. | **admin:zero-password-login** |
| Provision a new dedicated Phase Two hosted Keycloak cluster — "spin up a cluster", "set up hosted Keycloak", "I need a new Phase Two instance", "get a managed Keycloak running". | **admin:cluster-setup** |
| Create a new deployment (realm) in an existing cluster — "add a deployment", "new realm in my cluster", or phrased indirectly: "I want to secure/isolate this app", "give this app its own tenant/bounded security context", "separate environment for staging vs production". Not cluster provisioning itself (that's `admin:cluster-setup`, use it first if no cluster exists) and not realm-level settings on a deployment that already exists (not covered by this skill). | **admin:cluster-create-deployment** |
| Route a user to their own company's identity provider based on their email domain, while everyone else keeps password login — "corporate SSO", "enterprise SSO", "let our customer log in with their company account", "redirect to my corporate IdP", "home realm discovery", "IdP discovery by email domain". Not a plain IdP button shown to everyone with no domain routing (that's `admin:idp-federation`, next row) and not restricting login to organization members (a different mechanism — see the two rows after that). | **admin:corporate-sso** |
| Add a built-in **consumer social login** button — "log in with Google", "add a GitHub login button", "sign in with Microsoft/Facebook", "social login", "OAuth login with \[Google/GitHub/Microsoft/Facebook/...\]". Client ID + secret only, no discovery/metadata URL. Not a company's own Workspace/Entra ID/Okta tenant (that's enterprise federation, next row — "Google" as a company SSO source means Google **Workspace SAML**, not this) and not domain-routed (`admin:corporate-sso` above). | **admin:social-login** |
| Broker a company's own enterprise identity provider as a login option — "connect Okta/Entra ID/Auth0/ADFS/PingOne/...", "set up SAML SSO with \[vendor\]", "add \[vendor\] as an identity provider", "OIDC/SAML federation with our IdP". Covers Entra ID, Auth0, ADFS, AWS SSO, Google Workspace, CyberArk, JumpCloud, OneLogin, Oracle, PingOne, Duo, Salesforce, LastPass, Cloudflare Access, Okta, and any other generic OIDC/SAML 2.0 IdP. Not domain-auto-routing (`admin:corporate-sso` — this intent creates the button, that one decides who gets redirected automatically) and not a consumer social button (`admin:social-login` above) and not LDAP/AD user federation (reading users from a directory — no MCP tool for that, point at the Phase Two console). | **admin:idp-federation** |
| Start login from an external portal **tile** so a user lands in ONE specific app already logged in — "Okta dashboard tile into my app", "Entra ID / My Apps tile", "IdP-initiated SSO", "unsolicited SAML login", "start login from Okta/Entra instead of the app". Advanced and opt-in: the tile targets a single client, chosen by a `{urlName}` path segment on the client (NOT by RelayState, which Keycloak discards on this path). Requires that vendor to already be brokered as a SAML IdP. Not plain "log in with Okta/Entra" (`admin:idp-federation` — one button, every client, app-initiated) and not domain routing (`admin:corporate-sso`). | **admin:idp-initiated-sso** |
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

### admin:email-otp-login
```
Read: references/admin-email-otp-login-{tooling}.md
  tooling=mcp  → references/admin-email-otp-login-mcp.md
  tooling=rest → references/admin-email-otp-login.md
```
Requires the p2-inc `keycloak-magic-link` extension (same jar as magic-link) for the
`ext-email-otp` authenticator. Unlike magic-link there is **no auto-created flow** — one has to
be authored, and its execution order AND identifier-step choice are load-bearing: an identifier
step (`ext-auth-username-auth-note`, NOT stock `auth-username-form` — the latter leaks account
existence via an "Invalid username or email" error) must run BEFORE `ext-email-otp`, which reads
the attempted username off the auth session rather than collecting an address itself.

### admin:password-email-otp-mfa
```
Read: references/admin-password-email-otp-mfa-{tooling}.md
  tooling=mcp  → references/admin-password-email-otp-mfa-mcp.md
  tooling=rest → references/admin-password-email-otp-mfa.md
```
Requires the p2-inc `keycloak-magic-link` extension, same as `admin:email-otp-login`. The first
step is deliberately `auth-username-password-form` (stock Keycloak) — the opposite choice from
`admin:email-otp-login`'s identifier-only step, and correct here specifically: the password must
gate the OTP, verified live to mean a wrong password never reaches `ext-email-otp` and never
sends mail. Don't route a "2FA" or "second factor" request here to the passwordless intent just
because both use `ext-email-otp` — check whether a password is supposed to remain required.

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

### admin:zero-password-login
```
Read: references/admin-zero-password-login-{tooling}.md
  tooling=mcp  → references/admin-zero-password-login-mcp.md
  tooling=rest → references/admin-zero-password-login.md
```
Requires the p2-inc `keycloak-magic-link` extension for `ext-magic-form` (WebAuthn itself is stock
Keycloak), so **half** of this flow depends on a jar — check before authoring. Don't answer this
with the auto-created `magic link` flow: that offers magic link only, no passkey path. The two
authenticators are ALTERNATIVE siblings and their order is load-bearing — `ext-magic-form` must be
the lower priority, or a user with no passkey lands on a ceremony they cannot complete. Verifying
the passkey half needs a real browser with a CDP virtual authenticator; the magic-link half is
scriptable over plain HTTP.

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

### admin:social-login
```
Read: references/admin-social-login-{tooling}.md
  tooling=mcp  → references/admin-social-login-mcp.md
  tooling=rest → references/admin-social-login.md
```
Then, for the specific vendor asked for, also read the matching per-vendor console walkthrough:
`references/idp/social-google.md`, `social-microsoft.md`, `social-github.md`, `social-facebook.md`.
For any other built-in provider (GitLab, Bitbucket, Instagram, X/Twitter, LinkedIn, Stack Overflow,
PayPal, OpenShift) there's no dedicated walkthrough yet — the mechanism is the same, say so plainly.

### admin:idp-federation
```
Read: references/admin-idp-federation-{tooling}.md
  tooling=mcp  → references/admin-idp-federation-mcp.md
  tooling=rest → references/admin-idp-federation.md
```
If the vendor is **Okta**, hand off to the `settingOktaIdentityProvider` skill instead — it's a
complete guided workflow, don't duplicate it here. For every other vendor, the mechanics file's own
Step 1 table maps to the matching per-vendor file under `references/idp/`: `entra-id.md`, `auth0.md`,
`adfs.md`, `aws.md`, `google-workspace.md`, `cyberark.md`, `duo.md`, `jumpcloud.md`, `lastpass.md`,
`onelogin.md`, `oracle.md`, `pingone.md`, `salesforce.md`, `cloudflare.md`. Read exactly the one
matching the developer's vendor — these are console click-paths, not tooling-specific, so the same
file serves both `mcp` and `rest` tooling. If asked about **LDAP/Active Directory** as a login
source, that's user federation, not brokering — say plainly this skill doesn't cover it (no MCP tool
exists for it) rather than routing it into a SAML/OIDC vendor file.

### admin:idp-initiated-sso
```
Read: references/admin-idp-initiated-sso-{tooling}.md
  tooling=mcp  → references/admin-idp-initiated-sso-mcp.md
  tooling=rest → references/admin-idp-initiated-sso.md
```
Then read exactly one vendor file: `references/idp/okta-idp-initiated.md` or
`references/idp/entra-idp-initiated.md` (console click-paths; tooling-agnostic).

Prerequisite: the vendor must ALREADY be brokered as a **SAML** identity provider — do
`admin:idp-federation` first if not. This mechanism is SAML-only; there is no OIDC-broker
equivalent. The two settings developers most often expect on the identity provider
(`IDP Initiated SSO URL Name`, `IDP Initiated SSO Relay State`) do **not** exist there — verified
against `SAMLIdentityProviderConfig`; both are **client** attributes. On tooling=mcp, note up front
that `createSamlClient` can only set them on a **newly created SAML** client: there is no
update-client tool, so an existing client — or an OIDC client, which needs REDIRECT-binding
attributes the tool can't produce — has to go through the `rest` file's steps instead. Say which
path you're on rather than switching silently.

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
