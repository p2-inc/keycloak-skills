# `keycloak` router — reference manifest

The [`../SKILL.md`](../SKILL.md) router dispatches to the files below. Each is loaded **on demand**
for a specific intent + tooling, never all at once.

## How the router reaches each file

- **Step 1** picks an **intent** (today: `admin:passwordless-magic-link`, `admin:email-otp-login`, `admin:password-email-otp-mfa`,
  `admin:passwordless-magic-link-org-restrict`, `admin:passwordless-passkey`,
  `admin:cluster-setup`, `admin:cluster-create-deployment`, `admin:corporate-sso`,
  `admin:social-login`, `admin:idp-federation`,
  `admin:org-restrict-login`, `admin:idp-org-restrict-login`).
- **Step 2** picks a **tooling** (`mcp` or `rest`).
- **Step 3** maps the intent + tooling to the `Read:` list below.

## Reference files

| File | Intent (tooling) | Status |
|---|---|---|
| `admin-passwordless-magic-link.md` | `admin:passwordless-magic-link` (tooling=`rest`) — turning on the p2-inc `keycloak-magic-link` provider's built-in flow via raw Admin REST: binding, realm SMTP config, the anti-enumeration behavior, and the create-user-if-none-exists trap | ✅ done |
| `admin-passwordless-magic-link-mcp.md` | `admin:passwordless-magic-link` (tooling=`mcp`) — same outcome, driven end-to-end through Keycloak MCP server tools (`setSmtpSettings`, `listFlowExecutions`, `setExecutionAuthenticatorConfig`, `bindRealmAuthenticationFlow`/`bindClientAuthenticationFlow`) | ✅ done |
| `admin-email-otp-login.md` | `admin:email-otp-login` (tooling=`rest`) — passwordless login by an emailed 6-digit code via `ext-email-otp` (p2-inc keycloak-magic-link, same jar as magic-link): authoring the flow since none ships auto-created, the load-bearing `ext-auth-username-auth-note` → `ext-email-otp` order (NOT stock `auth-username-form`, which was verified live to leak account existence via an "Invalid username or email" error before `ext-email-otp` ever runs), the single `ext-magic-create-nonexistent-user` option (default `false` here, unlike magic-link's `true`), realm SMTP, and why brute-force protection matters for a 6-digit code | ✅ done |
| `admin-email-otp-login-mcp.md` | `admin:email-otp-login` (tooling=`mcp`) — same outcome through `importAuthenticationFlow`, `setSmtpSettings`, `setBruteForceProtection`, `listFlowExecutions`/`setExecutionAuthenticatorConfig` (all confirmed present on the server) | ✅ done |
| `admin-password-email-otp-mfa.md` | `admin:password-email-otp-mfa` (tooling=`rest`) — password login hardened with `ext-email-otp` as a second factor: `auth-username-password-form` (stock Keycloak, the gate) then `ext-email-otp`, verified live that a wrong password never reaches the OTP step and never sends mail, and why this is the one place `auth-username-password-form` is the *right* identifier step (the opposite of the passwordless intent above) | ✅ done |
| `admin-password-email-otp-mfa-mcp.md` | `admin:password-email-otp-mfa` (tooling=`mcp`) — same outcome through `importAuthenticationFlow`, `setSmtpSettings`, `listFlowExecutions`/`setExecutionAuthenticatorConfig` | ✅ done |
| `admin-passwordless-magic-link-org-restrict.md` | `admin:passwordless-magic-link-org-restrict` (tooling=`rest`) — magic-link login gated on organization membership: a custom flow (`ext-auth-username-auth-note` → `ext-select-org` → `ext-magic-form`, in that order — the org check must run *before* the send) authored via `authentication-flow/import` (or the manual sequence), why the ordering is load-bearing, and reusing the `ext-magic-create-nonexistent-user=false` trap from plain magic-link | ✅ done |
| `admin-passwordless-magic-link-org-restrict-mcp.md` | `admin:passwordless-magic-link-org-restrict` (tooling=`mcp`) — same outcome via `importAuthenticationFlow` plus the org-restrict-login tool set (`createOrganization`, membership, `setSmtpSettings`) | ✅ done |
| `admin-passwordless-passkey-mcp.md` | `admin:passwordless-passkey` (tooling=`mcp`) — passkey-only WebAuthn login: the realm's WebAuthn PASSWORDLESS policy (`setWebAuthnPasswordlessPolicy`), authoring and binding a passkey-only flow (`importAuthenticationFlow` when the keycloak-atomic-auth-flows extension is present, documented manual REST sequence otherwise), and the credential-bootstrap problem for a zero-credential user (`sendRequiredActionEmail`) | ✅ done |
| `admin-passwordless-passkey.md` | `admin:passwordless-passkey` (tooling=`rest`) — same outcome via raw Admin REST: realm-representation PUT for the WebAuthn PASSWORDLESS policy and SMTP, authoring/binding the flow, and `execute-actions-email` for credential bootstrap | ✅ done |
| `cluster-setup-mcp.md` | `admin:cluster-setup` (tooling=`mcp` only) — provisioning a dedicated Phase Two cluster: org/region/tier/billing selection, Stripe checkout handoff (never completes payment), polling to `ACTIVE`, optional first deployment and custom domain | ✅ done |
| `cluster-create-deployment-mcp.md` | `admin:cluster-create-deployment` (tooling=`mcp` only) — creating a new deployment (realm) in an existing `ACTIVE` cluster, including recognizing "isolate/secure this app" as a request for a new realm | ✅ done |
| `admin-corporate-sso-mcp.md` | `admin:corporate-sso` (tooling=`mcp`) — routing by email domain via organizations (`linkIdentityProviderToOrganization`), the `homeIdp`/`homeIdp with orgs-check` custom flows and `forwardToLinkedIdp`, why an IdP-redirector execution is the wrong answer | ✅ done |
| `admin-corporate-sso.md` | `admin:corporate-sso` (tooling=`rest`) — same outcome via raw Admin REST: `organizationsEnabled`, creating the IdP and the verified-domain organization, linking them, and when the built-in `browser` flow already routes without any custom flow at all | ✅ done |
| `admin-social-login-mcp.md` | `admin:social-login` (tooling=`mcp`) — built-in consumer social providers (`createSocialIdp`); the fixed `providerId` list confirmed against Keycloak's `org.keycloak.social` package, the hardcoded `trustEmail=true`, and the provider-specific config keys (`hostedDomain`, `tenantId`, `fetchedFields`, `key`, `sandbox`) that the tool cannot set | ✅ done |
| `admin-social-login.md` | `admin:social-login` (tooling=`rest`) — same outcome via raw Admin REST `identity-provider/instances`, including how to set the provider-specific config keys the MCP tool can't | ✅ done |
| `admin-idp-federation-mcp.md` | `admin:idp-federation` (tooling=`mcp`) — enterprise IdP brokering via `createOidcIdp`/`createSamlIdp`; the vendor routing table, the deterministic Keycloak SP-value computation that unblocks the vendor-console-first ordering most SAML vendors need, and the file-vs-URL metadata split | ✅ done |
| `admin-idp-federation.md` | `admin:idp-federation` (tooling=`rest`) — same outcome via raw Admin REST `identity-provider/import-config` + `instances` | ✅ done |
| `admin-org-restrict-login-mcp.md` | `admin:org-restrict-login` (tooling=`mcp`) — restricting login to one organization's members via `ext-select-org` (`match_by_org_name`), authored+bound in one call with `importAuthenticationFlow` (needs the keycloak-atomic-auth-flows extension; offers it, falls back to a manual REST sequence); explicit about the `account_hint`/`prompt=select_account` trigger requirement | ✅ done |
| `admin-org-restrict-login.md` | `admin:org-restrict-login` (tooling=`rest`) — same outcome via raw Admin REST: creating the organization and adding members through the keycloak-orgs surface (`/realms/{realm}/orgs`), configuring `ext-select-org`, and authoring/binding the flow (atomic-flows extension or the manual sequence) | ✅ done |
| `admin-idp-org-restrict-login-mcp.md` | `admin:idp-org-restrict-login` (tooling=`mcp`) — gating FEDERATED login on organization membership: the org-owned IdP link that makes the gate work at all, a post-broker flow containing `ext-select-org` bound as the IdP's `postBrokerLoginFlowAlias` (the stock post-broker flow has none, so binding it gates nothing) | ✅ done |
| `admin-idp-org-restrict-login.md` | `admin:idp-org-restrict-login` (tooling=`rest`) — same outcome via raw Admin REST, including the atomic-flows payload details (`postLoginFlowBinding`, stripped `ifResourceExists`, hash-prefixed aliases) | ✅ done |

Both `admin-password-email-otp-mfa*.md` files reference
[`assets/username-password-email-otp-flow.partial-import.json`](../assets/username-password-email-otp-flow.partial-import.json)
— structurally almost identical to the plain email-OTP asset, but with `auth-username-password-form`
in place of `ext-auth-username-auth-note` as the first execution. That single substitution is the
entire difference between "passwordless" and "password + second factor"; verified live (correct
password → OTP sent; wrong password → rejected before `ext-email-otp` runs, no mail sent).

Both `admin-email-otp-login*.md` files reference
[`assets/email-otp-flow.partial-import.json`](../assets/email-otp-flow.partial-import.json). Its
`ext-magic-create-nonexistent-user: "false"` is verified-correct rather than a magic-link
copy-paste: `ext-email-otp` genuinely shares that config key (a single constant in the extension)
and it is that authenticator's ONLY option. Setting it explicitly is documentation — the runtime
default is already `false` for email OTP, unlike `ext-magic-form`'s `true`.

Both `admin-passwordless-magic-link-org-restrict*.md` files reference the shared asset
[`assets/select-organization-magic-link.partial-import.json`](../assets/select-organization-magic-link.partial-import.json)
— note its `ext-magic-form` config carries a real, verified value
(`ext-magic-create-nonexistent-user=false`), not a placeholder; the same key the plain
magic-link references already document.

Both `admin-corporate-sso*.md` files reference shared assets/scripts at the skill root:
`assets/home-idp.partial-import.json`, `assets/home-idp-with-orgs-check.partial-import.json`, and
`scripts/browser_login.py` (tooling-agnostic — verifies routing over plain HTTP either way).
`admin-org-restrict-login-mcp.md` references `assets/org-browser-flow-by-org-name.partial-import.json`
and `assets/org-browser-flow-by-org-id.partial-import.json` — two alternative *configurations* of
the same flow alias, not two coexisting flows; pick one up front.

`admin-social-login*.md` and `admin-idp-federation*.md` both point into `references/idp/` for
per-vendor console click-paths — **tooling-agnostic**, since which console buttons a developer
clicks doesn't change based on whether Keycloak is driven via MCP or REST: `social-google.md`,
`social-microsoft.md`, `social-github.md`, `social-facebook.md` (consumer social login) and
`entra-id.md`, `auth0.md`, `adfs.md`, `aws.md`, `google-workspace.md`, `cyberark.md`, `duo.md`,
`jumpcloud.md`, `lastpass.md`, `onelogin.md`, `oracle.md`, `pingone.md`, `salesforce.md`,
`cloudflare.md` (enterprise federation). The 14 enterprise files (Auth0 and Salesforce each cover
both their OIDC and SAML wizards in one file) are verified against
[p2-inc/idp-wizard](https://github.com/p2-inc/idp-wizard)'s actual step content — vendor console
menu paths, exact field names, and load-bearing ordering (JumpCloud's is reversed relative to every
other vendor: Keycloak's SP values go in *first*, its metadata export comes out *last*) — not
recalled generically. **Okta is deliberately absent** — it hands off to `settingOktaIdentityProvider`
per `SKILL.md`'s Step 3, so no `okta.md` exists here; don't add one without first checking whether
the dedicated skill should absorb the content instead. The remaining built-in social providers
(GitLab, Bitbucket, Instagram, X/Twitter, LinkedIn, Stack Overflow, PayPal, OpenShift) and any
generic OIDC/SAML vendor outside the 14 above have no dedicated walkthrough yet — say so plainly
per the "growing this router" convention below rather than improvising one.

**Note on the `*.partial-import.json` asset names**: that naming is now misleading. Keycloak's
`partialImport` endpoint has **no handler for authentication flows** and silently ignores them
(HTTP 200, nothing created, no error) — verified against Keycloak's own `PartialImportManager`
source and tested on two versions. The asset *contents* are still correct; they're consumed either
by the [keycloak-atomic-auth-flows](https://github.com/p2-inc/keycloak-atomic-auth-flows)
extension's `/authentication-flow/import` endpoint (which also binds, in the same call) or by a
manual create-flow/add-execution REST sequence. Renaming the assets is worth doing but hasn't been,
to avoid churning every reference that links them.

`admin:cluster-setup` and `admin:cluster-create-deployment` have **no `rest` reference file by
design** — they're Phase Two SaaS control-plane capabilities (cluster/deployment lifecycle) with
no self-managed-Keycloak equivalent to document, unlike the passwordless intents above where
`rest` is a genuine second tooling path to the same outcome. `SKILL.md`'s Step 3 says so plainly
rather than treating it as a gap. `admin:org-restrict-login` now has both tooling paths; note
both still require the p2-inc `keycloak-orgs` extension, which is a *deployment* prerequisite
rather than a tooling choice. The same holds for `admin:idp-org-restrict-login`, which additionally
binds to the identity provider's post-broker login flow rather than the realm/client browser flow.

## Authoring conventions

- **Router carries no domain content.** Steps and values live in references, not `SKILL.md`.
- **One intent, multiple tooling files — not multiple skills.** `admin:passwordless-magic-link` has
  two reference files (`-mcp` and plain) because the *outcome* is identical and only the driving
  mechanism (MCP tools vs. raw REST) differs. Prefer this shape — one intent, a `{tooling}`-suffixed
  file per mechanism — over splitting into separate skills whenever a capability has more than one
  valid tooling path to the same result.
- **Confirm live MCP tool names before writing a new reference** — don't assume a tool exists on
  the Keycloak MCP server without checking what's actually exposed. `admin-passwordless-magic-link-mcp.md`
  calls out which tools (`setSmtpSettings`, `listFlowExecutions`, `setExecutionAuthenticatorConfig`)
  are recent additions specifically so a missing tool reads as a real gap, not a skill bug.
- **Growing this router**: every capability here so far is genuine, verified content — not
  speculative scaffolding. Each new capability (plugin development, realm provisioning, IdP
  federation, clients, organizations, ...) should only get a `Read:` entry once it's actually
  written and verified the same way, not stubbed out ahead of time.
- **Uncovered requests become issues, not guesses.** `SKILL.md`'s "No intent matches" section is the
  intended feedback loop for this list — when the router can't route something, it offers to file a
  gap issue in this repo instead of forcing the request through `admin:passwordless-magic-link`.
  Each such issue carries the developer's **verbatim prompt**, not a paraphrase — that's what makes
  the backlog usable: a new intent row's "plain language" column should be written from the actual
  phrasing developers used, not a guess at how they'd phrase it.
