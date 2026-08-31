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
  organization + verified-domain + linked-IdP mechanism that performs the discovery, the
  `homeIdp` / `homeIdp with orgs-check` flows and the `forwardToLinkedIdp=true` setting the
  redirect depends on, why an identity-provider-redirector execution is the wrong answer, and
  how to verify the routing by actually logging in. Not user federation
  (connectingUserStore), not plain identity brokering with a login-page button
  (connectingIdentityProvider), and not binding organization/passwordless flows generally
  (bindingAuthenticationFlow).
---

<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# Corporate SSO by email domain

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

## Tools this skill drives (Keycloak MCP server)

| Purpose | Tool |
|---|---|
| Identify caller / realm | `whoAmI` |
| Find or create the customer's organization | `admin:organizations` intent |
| Create the corporate IdP | `createOidcIdp` / `createSamlIdp` / `settingOktaIdentityProvider` |
| **Link the IdP to the organization** | `linkIdentityProviderToOrganization` |
| See what flows exist | `listAuthenticationFlows` |
| Bind the flow | `bindRealmAuthenticationFlow` / `bindClientAuthenticationFlow` |
| Confirm bindings | `getAuthenticationBindings` |

Capture **`deploymentId`** and **`deploymentRealm`** and reuse them on every call.

> **Drive this through the MCP tools.** If a required tool is unavailable in this deployment,
> say so and stop. Do **not** silently substitute Admin REST calls — an unreported switch hides
> the fact that the tooling is incomplete, and leaves the user unable to reproduce what you
> did. Only fall back to REST if the user confirms this is not a Phase Two realm (see the
> appendix).

## The hard prerequisite — establish this first

**Discovery is organization-driven.** The discoverer looks up an organization by the user's
email domain and forwards to *that organization's linked IdP*. There is no standalone
domain-to-IdP setting anywhere. So the first question is:

> **"Is the company modelled as an organization in this realm, with a verified email domain,
> and is the IdP linked to it?"**

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

## Which flow to bind

| The user also wants… | Flow | Asset |
|---|---|---|
| Just the corporate-IdP redirect | **`homeIdp`** | [`assets/home-idp.partial-import.json`](assets/home-idp.partial-import.json) |
| The redirect **and** to be treated as a member of that organization | **`homeIdp with orgs-check`** | [`assets/home-idp-with-orgs-check.partial-import.json`](assets/home-idp-with-orgs-check.partial-import.json) |

Both are custom flows. Confirm with `listAuthenticationFlows`; if the one you need is missing,
apply the bundled asset via the admin console (Realm Settings → Action → Partial import) or
`kcadm.sh create partialImport` — there is no MCP tool that performs the import, so this is a
manual step you must hand to the user rather than perform.

**Both assets deliberately set `forwardToLinkedIdp=true`.** The authenticator's factory default
is `false`, which silently prevents any redirect at all — the single most likely cause of "I
configured everything and it still shows the password form".

Then bind exactly as in `bindingAuthenticationFlow`:
`bindRealmAuthenticationFlow(bindingType="browser", flowAlias="homeIdp")`, or
`bindClientAuthenticationFlow` for a single application. Binding alone does nothing if the
prerequisite above is not satisfied.

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

`scripts/browser_login.py` drives the whole round trip and prints where each step went.

Afterwards, a correctly federated user has a non-empty federated identity and **no** password
credential in your realm. That distinction matters: hand-creating local accounts with matching
email addresses reproduces some of the behaviour while being the opposite of federation.

## Provider settings that bite

- **`trustEmail: true`** — without it a brokered user is asked to verify an email the customer
  already verified, stalling first login. Set it when you trust the provider.
- **The redirect URI the customer must whitelist** is
  `{base}/realms/{realm}/broker/{alias}/endpoint`. It contains the alias, so choose the alias
  *before* asking them to whitelist anything.
- **`hideOnLogin`** — tempting, to keep one customer's button off a shared login page.
  Measured: setting it true removes the route for the **matched** domain too, leaving those
  users with no password field *and* no way forward. Leave it visible unless you have verified
  the matched-domain path still works.
- **`syncMode`** — `IMPORT` copies profile fields on first login only; `FORCE` refreshes them
  on every login, usually right when the customer's directory is authoritative.
- **First broker login** — the default flow reviews the profile when fields are missing and can
  prompt to link an existing local account with the same email. With `trustEmail` and a
  provider sending `email`, `given_name` and `family_name`, it passes through silently.

## Not organization *restriction*

This is an automatic redirect, not a membership gate. A user whose email domain matches no
organization falls through to the password fallback. If the ask is "only members of this
organization may log in at all", that is a different mechanism with a significant caveat — see
`bindingAuthenticationFlow`, Stage 4.

## Troubleshooting

| Symptom | Cause |
|---|---|
| Matched domain still shows the password form | `forwardToLinkedIdp` left at its `false` default, or the IdP is not linked to the organization |
| SSO button shown to everyone, nothing routes | Provider created but not linked to an organization |
| Domain never matches | The organization's domain is not marked verified |
| Everyone gets forwarded to the provider | An identity-provider-redirector execution in the bound flow |
| Matched domain gets neither password nor route | `hideOnLogin` is true on the provider |
| A required MCP tool is missing | Report it and stop; do not switch to REST unsolicited |
| `400` "Cookie not found" while scripting | `Secure` cookies not sent over http by the client |
| `invalid_redirect_uri` at the customer's provider | They whitelisted a different alias than the one created |

## Appendix — non-Phase Two realms

Stock Keycloak 26 has the same mechanism under a different name: the `organization` feature
flag, a realm `organizationsEnabled` switch, `POST /admin/realms/{realm}/organizations` with
`domains:[{name,verified:true}]`, and
`POST /admin/realms/{realm}/organizations/{orgId}/identity-providers` (body is a bare JSON
string holding the alias). The built-in `browser` flow then routes without any custom flow.
Note the redirect there is not silent for a first-time user — they are shown the provider as a
link. Use this only when the user has confirmed there is no Phase Two deployment and no MCP
server; otherwise the tools above are the supported path.
