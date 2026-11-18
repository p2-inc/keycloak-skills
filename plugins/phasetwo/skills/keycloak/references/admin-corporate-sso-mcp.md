<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

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
| Bind the flow | `bindRealmAuthenticationFlow` / `bindClientAuthenticationFlow` |
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
> did. Only fall back to `admin-corporate-sso.md`'s REST steps if the user confirms this is not
> a Phase Two realm.

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
  link costs nothing.

Measured on Phase Two's Keycloak 26.8.2 image (keycloak-orgs 0.199), all with unverified
domains:

- An org without domains, linked with `domains`, did not route.
- Adding the domain to that org made it route.
- An org holding the domain, linked without `domains`, routed.

Since keycloak-orgs 0.199 the organization's domains also gate first login: the realm's
`first broker login` flow carries a REQUIRED `ext-auth-org-domain-fbl-verifier`
(GHSA-gvcc-4vw2-6wvr), so a first login through an IdP linked to an organization stops on "Valid
identity email domain not found." unless the email the IdP sends is at one of that organization's
domains.

Two things must both be true, and each fails silently on its own. The flow in the next section
must also be bound.

| Missing | Symptom |
|---|---|
| The organization does not hold the customer's email domain | Discovery has nothing to match, even if the link carried the domain |
| The IdP is created but **not linked** to the organization | The provider works, but the login page just shows an SSO button to everybody — no routing |

The second is the one that gets skipped: **creating an IdP does not associate it with any
organization.** `linkIdentityProviderToOrganization` takes the `orgId`, the `idpAlias`, and the
organization's email `domains`. Without that call, Home IdP Discovery will never find the IdP
for that domain, no matter how correct everything else is.

Confirm the link exists before moving on — do not assume it from a successful IdP creation.

**"Verified" is real DNS domain-ownership proof, not a flag you set — and triggering it is
deliberately not exposed here.** Adding a domain to an organization (via `createDeploymentOrganization`'s
`domains` argument, or later) does not mark it verified. The extension verifies ownership by
checking for a specific TXT record — something like `_org-domain-ownership.<domain>` — resolving
to a value derived from the domain and the organization's ID, and only flips `verified` to `true`
once that DNS record is found. **This is a Phase Two-managed process, not something this skill (or
any MCP tool) triggers.** Use `listDeploymentOrganizationDomains` to check a domain's current status and get
the `recordKey`/`recordValue` it needs, then direct the customer to Phase Two's own process for
getting it verified. Don't look for, or improvise, a way to verify it yourself. Verification is
not a prerequisite for this intent: an unverified domain routes with the bundled flows.

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
200, nothing created, no error.

`importAuthenticationFlow` requires the [p2-inc keycloak-atomic-auth-flows](https://github.com/p2-inc/keycloak-atomic-auth-flows)
extension and returns a clear 404 if it's missing. Offer installing it — one jar, one call instead
of many — as the one-shot. **The component path is the default and always available, entirely
inside MCP**: `addFlow` → `addSubFlow` for the forms sub-flow →
`addAuthenticator` for each leaf step (`auth-cookie`, `auth-spnego`,
`identity-provider-redirector`, `ext-auth-home-idp-discovery`) → `setExecutionRequirement` on
each → bind. There is no raw-REST or credentials-from-the-user step needed here; report a dead
end only if one of these tools itself is unavailable on this MCP server.

**Pass `priority` explicitly on every `addSubFlow`/`addAuthenticator`
call.** Both APPEND when priority is omitted — landing at `(last sibling's priority + 1)` — so
creating the forms sub-flow before `auth-cookie` exists puts it first. `priority` in the body is
honoured only from Keycloak 25 onward; older versions need `raiseExecutionPriority`/
`lowerExecutionPriority` to repair the order afterward. Read it back with `listFlowExecutions`
before calling the flow done.

Note the atomic-import path hash-prefixes the created alias, so read the real name back rather
than assuming the asset's name — the manual-sequence path does not have this issue, since you
choose the alias yourself.

Both assets set `forwardToLinkedIdp=true`. It decides only whether discovery consults the user's
existing federated links. When it is on, a provider the user is already linked to wins over the
first provider their domain matches, and a linked user is forwarded to it even when their domain
matches no organization. With one provider per organization, and users at the organization's
domains, it changes nothing: measured on Phase Two's 26.8.2 image (keycloak-orgs 0.199),
first-time and returning users were forwarded alike at its default of `false`.

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
  `https` or `localhost`; some other HTTP clients need the Secure flag cleared on each response.
- A user who has **never** federated and one who **already** has a federated identity are sent
  onward differently (an offered link versus an immediate redirect with a `login_hint`). Follow
  both, or a test passes on the first login and fails on the second.

The routing check needs no admin access, so plain HTTP works on either tooling path:

```bash
BASE=http://localhost:8080/auth; REALM=<realm>; JAR=$(mktemp)
form_action() { grep -o 'action="[^"]*"' | head -1 | sed -e 's/^action="//' -e 's/"$//' -e 's/&amp;/\&/g'; }
login_page() {   # fresh login page for this client → prints the form's POST URL
  curl -s -G -c "$JAR" -b "$JAR" "$BASE/realms/$REALM/protocol/openid-connect/auth" \
    --data-urlencode "client_id=<client-id>" --data-urlencode "redirect_uri=<app-redirect-uri>" \
    -d response_type=code -d scope=openid \
    -d code_challenge_method=S256 -d code_challenge=E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM \
    | form_action   # a fixed PKCE challenge is fine: the code is never redeemed
}
# Routed domain: expect a 302 whose redirect URL is the customer's IdP (or a broker endpoint
# that leads there), not a page with a password field
curl -s -c "$JAR" -b "$JAR" -o /dev/null -w '%{http_code} %{redirect_url}\n' \
  --data-urlencode "username=someone@customer.example" "$(login_page)"
# Any other domain: expect 200 and a password field (prints 1 or more)
curl -s -c "$JAR" -b "$JAR" --data-urlencode "username=someone@other.example" \
  "$(login_page)" | grep -c 'type="password"'
```

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
| Matched domain still shows the password form | No `ext-auth-home-idp-discovery` execution in the flow in effect: the stock `browser` flow has none. Check `getAuthenticationBindings`, then the bound flow's executions with `listFlowExecutions` |
| A domain never routes although the IdP is linked | The organization does not hold that domain; the link's `domains` alone do not route. `createDeploymentOrganization` sets domains only at creation, and no MCP tool edits them later. Report that gap and stop: the fix is `PUT /realms/{realm}/orgs/{org-id}` with the domain added, which the user runs |
| SSO button shown to everyone, nothing routes | Provider created but not linked to an organization |
| Everyone gets forwarded to the provider | An identity-provider-redirector execution in the bound flow |
| A required MCP tool is missing | Report it and stop; do not switch to REST unsolicited |
| `400` "Cookie not found" while scripting | `Secure` cookies not sent over http by the client |
| `invalid_redirect_uri` at the customer's provider | They whitelisted a different alias than the one created |
