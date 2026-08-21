# Corporate SSO by email domain — via the Keycloak MCP server

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
followed by a call like `listOrganizations` erroring out (rather than returning an empty list)
is a sign the extension isn't installed on this server — say so plainly rather than assuming the
MCP tools below will work.

## Tools this skill drives (Keycloak MCP server)

| Purpose | Tool |
|---|---|
| Identify caller / realm | `whoAmI` |
| Create the customer's organization | `createOrganization` (see the domain-verification caveat below — **before** relying on it) |
| Create the corporate IdP | `createOidcIdp` / `createSamlIdp` |
| **Link the IdP to the organization** | `linkIdentityProviderToOrganization` — **pass `domains`**, or routing stays dead |
| See what flows exist | `listAuthenticationFlows` |
| Bind the flow | `bindRealmAuthenticationFlow` / `bindClientAuthenticationFlow` |
| Confirm bindings | `getAuthenticationBindings` |

Capture **`deploymentId`** and **`deploymentRealm`** and reuse them on every call.

> **Drive this through the MCP tools.** If a required tool is unavailable in this deployment,
> say so and stop. Do **not** silently substitute Admin REST calls — an unreported switch hides
> the fact that the tooling is incomplete, and leaves the user unable to reproduce what you
> did. Only fall back to `admin-corporate-sso.md`'s REST steps if the user confirms this is not
> a Phase Two realm.

## The hard prerequisite — establish this first

**Discovery matches on the IdP's own domain list, written when you link it.** The
domains you pass to `linkIdentityProviderToOrganization` land on the IdP as the config key
`home.idp.discovery.domains`, and that is what the discoverer compares the typed address
against. So the first question is:

> **"Is the company modelled as an organization in this realm, and is the IdP linked to it
> *with the domains passed on the link*?"**

Two corollaries that save a long debugging session:

- **Domain verification is irrelevant to routing.** Verified domains feed a different, optional
  authenticator (`ext-auth-org-id-verifier`). An unverified domain routes perfectly well.
- **Adding a domain to the organization does not route anything.** The organization's `domains`
  and the link's `domains` are separate lists; only the latter drives discovery. Pass the
  domains to `linkIdentityProviderToOrganization` even if the org already lists them.

Three things must all be true, and each fails silently on its own:

| Missing | Symptom |
|---|---|
| The organization does not hold the customer's email domain | Discovery has nothing to match |
| The domain is present but **not verified** | Discovery never matches that domain |
| The IdP is created but **not linked** to the organization | The provider works, but the login page just shows an SSO button to everybody — no routing |

The third is the one that gets skipped: **creating an IdP does not associate it with any
organization.** `linkIdentityProviderToOrganization` takes the `orgId`, the `idpAlias`, and the
organization's email `domains`. Without that call, Home IdP Discovery will never find the IdP
for that domain, no matter how correct everything else is.

Confirm the link exists before moving on — do not assume it from a successful IdP creation.

**"Verified" is real DNS domain-ownership proof, not a flag you set — and triggering it is
deliberately not exposed here.** Adding a domain to an organization (via `createOrganization`'s
`domains` argument, or later) does not mark it verified. The extension verifies ownership by
checking for a specific TXT record — something like `_org-domain-ownership.<domain>` — resolving
to a value derived from the domain and the organization's ID, and only flips `verified` to `true`
once that DNS record is found. **This is a Phase Two-managed process, not something this skill (or
any MCP tool) triggers.** Use `listOrganizationDomains` to check a domain's current status and get
the `recordKey`/`recordValue` it needs, then direct the customer to Phase Two's own process for
getting it verified — don't look for (or improvise) a way to verify it yourself, and don't treat
an added-but-unverified domain as ready for discovery.

## Which flow to bind

| The user also wants… | Flow | Asset |
|---|---|---|
| Just the corporate-IdP redirect, by email domain | **`homeIdp`** | [`../assets/home-idp.partial-import.json`](../assets/home-idp.partial-import.json) |
| The redirect **and** to be treated as a member of that organization | **`homeIdp with orgs-check`** | [`../assets/home-idp-with-orgs-check.partial-import.json`](../assets/home-idp-with-orgs-check.partial-import.json) |

Both drive the redirect through the **`ext-auth-home-idp-discovery`** authenticator (config alias
`home-idp-discovery`). This is what actually performs the org/domain/link lookup described above
— confirm it's present in whichever flow you bind, not just that *a* custom flow exists.

Both are custom flows. Confirm with `listAuthenticationFlows`; if the one you need is missing,
author it with **`importAuthenticationFlow`**, passing the asset's `authenticationFlows` and
`authenticatorConfig` arrays plus the binding (`browserFlowBinding`, or `clientFlowBinding` for a
single client) in the same payload.

**Do not use Keycloak's `partialImport` endpoint (or the admin console's "Partial import" action)
for flows** — it has no handler for authentication flows at all and silently ignores them: HTTP
200, nothing created, no error. `importAuthenticationFlow` instead requires the
[p2-inc keycloak-atomic-auth-flows](https://github.com/p2-inc/keycloak-atomic-auth-flows)
extension on the target Keycloak; it returns a clear 404 if that's missing, in which case offer
installing it (one jar, one call instead of a long manual create-flow/add-execution/set-requirement
sequence) rather than silently switching approaches. Note the extension hash-prefixes the created
alias, so read the real name back rather than assuming the asset's name.

**Both assets deliberately set `forwardToLinkedIdp=true`.** The authenticator's factory default
is `false`, which silently prevents any redirect at all — the single most likely cause of "I
configured everything and it still shows the password form".

**Not the same as `Org Browser Flow by Org Name`**
([`../assets/org-browser-flow-by-org-name.partial-import.json`](../assets/org-browser-flow-by-org-name.partial-import.json)).
That flow uses a different authenticator (`ext-select-org`, config `match-by-org-name`) to select
an organization by an explicit `account_hint=<org-name>` the application passes — not by the
domain of an email address typed on the login page. It's the right tool for "the app already
knows which org this user belongs to and wants login restricted to it," not for "figure out which
company this person is from, from their email." Don't substitute one for the other.

Then bind: `bindRealmAuthenticationFlow(bindingType="browser", flowAlias="homeIdp")`, or
`bindClientAuthenticationFlow` for a single application (same two binding surfaces as every other
flow-binding intent in this router). Binding alone does nothing if the prerequisite above is not
satisfied.

**A custom flow is always required here** — unlike Keycloak's own native Organizations feature
(which Phase Two does not use, see above), this extension's IdP discovery is an authenticator you
author into a flow, not something the stock `browser` flow does automatically once organizations
exist. Don't assume domain routing "just works" once the organization/domain/link pieces are in
place — the flow still has to be authored and bound.

## Verify by logging in, not by reading configuration

Every setting here can be correct-looking and inert, and no tool reports routing — routing is
behaviour. Have the user (or a script) perform a real login twice:

| Submit on the login page | Expect |
|---|---|
| an address at the customer's verified domain | **no password field**; the browser is sent to the customer's IdP |
| an address at any other domain | **a password field**, and password login still completes |

The second row is not optional. It is what distinguishes correct domain discovery from a
redirector that hijacks every login, and it is the check people skip.

If you are scripting this rather than clicking through it, two details will otherwise cost you
an afternoon:

- Keycloak sets `AUTH_SESSION_ID` and `KC_RESTART` as `Secure; SameSite=None`. Browsers send
  them over `http://localhost` anyway — loopback is a secure context — but HTTP clients
  typically refuse, and every form POST then returns `400` *"Cookie not found. Please make sure
  cookies are enabled in your browser."* Clear the flag on each response
  (`cookie.secure = False` in Python `requests`).
- A user who has **never** federated and one who **already** has a federated identity are sent
  onward differently (an offered link versus an immediate redirect with a `login_hint`). Follow
  both, or a test passes on the first login and fails on the second.

[`../scripts/browser_login.py`](../scripts/browser_login.py) drives the whole round trip and
prints where each step went — usable against either tooling path since it only speaks plain
HTTP, not MCP.

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
- **`syncMode`** — `IMPORT` copies profile fields on first login only; `FORCE` refreshes them
  on every login, usually right when the customer's directory is authoritative.
- **First broker login** — the default flow reviews the profile when fields are missing and can
  prompt to link an existing local account with the same email. With `trustEmail` and a
  provider sending `email`, `given_name` and `family_name`, it passes through silently.

## Not organization *restriction*

This is an automatic redirect, not a membership gate. A user whose email domain matches no
organization falls through to the password fallback. If the ask is "only members of this
organization may log in at all", that is a different, related mechanism not covered by this
intent — treat it as a separate request and offer to file a gap issue (see `SKILL.md`'s "No
intent matches").

## Troubleshooting

| Symptom | Cause |
|---|---|
| Matched domain still shows the password form | `forwardToLinkedIdp` left at its `false` default, or the IdP is not linked to the organization |
| Matched domain gets neither password nor route | Linked without `domains`, so the IdP is hidden but unroutable — re-link passing the domains |
| SSO button shown to everyone, nothing routes | Provider created but not linked to an organization |
| Domain never matches | The domains were added to the organization but not passed on the link (verification is not the cause) |
| Everyone gets forwarded to the provider | An identity-provider-redirector execution in the bound flow |
| A required MCP tool is missing | Report it and stop; do not switch to REST unsolicited |
| `400` "Cookie not found" while scripting | `Secure` cookies not sent over http by the client |
| `invalid_redirect_uri` at the customer's provider | They whitelisted a different alias than the one created |
