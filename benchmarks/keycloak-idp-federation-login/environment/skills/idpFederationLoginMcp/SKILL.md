---
name: idpFederationLoginMcp
description: >-
  Broker a partner company's own OIDC identity provider into a Phase Two hosted Keycloak
  realm as a plain "log in with <partner>" button - driven through the Keycloak MCP
  server. Use this whenever someone asks to "let our partner's staff log in with their
  own account", "add a login-with-X button", "federate a partner's identity provider",
  or "broker an external OIDC provider" - with NO organization membership requirement
  and NO domain-based auto-routing attached. Covers createOidcIdp, mapping claims onto
  the brokered user with addIdpAttributeMapper, and verifying with more than one real
  user so no hidden per-user gate slips in. Not admin:org-restrict-login /
  admin:idp-org-restrict-login (those gate on organization membership) and not
  admin:corporate-sso-login (that routes by email domain) - this is an unconditional
  login button, nothing more.
---

# Broker a partner's OIDC identity provider as a plain login button — via the Keycloak MCP server

## What this is, and what it is NOT

The user authenticates at an **external identity provider** the partner company
operates, and gets in with nothing more than valid credentials there. This is the
simplest of three adjacent capabilities that all touch identity providers and are easy
to conflate:

| Capability | Extra requirement beyond valid credentials |
|---|---|
| **This one** | None. Any valid account at the partner's IdP gets in. |
| `admin:corporate-sso-login` | The user must be routed there by their email domain (organization "verified domains" + Home IdP Discovery). |
| `admin:org-restrict-login` / `admin:idp-org-restrict-login` | The user must belong to a specific organization, checked via `account_hint` and a custom post-broker flow. |

**The trap**: an agent that has just solved (or read about) either of the other two
reaches reflexively for an `account_hint` requirement, an organization link, or a
domain check here. That produces something that *looks* done — a real user can log in —
but fails the actual ask, because it also blocks (or silently gates) users the caller
never meant to restrict. If the request doesn't mention organizations, teams, or
routing by email domain, don't add any of that machinery.

## Tools this skill drives (Keycloak MCP server)

| Purpose | Tool |
|---|---|
| Identify caller / realm | `whoAmI` |
| Broker the partner's OIDC provider | `createOidcIdp` |
| Map claims onto the brokered user | `addIdpAttributeMapper` |
| Verify | `listIdentityProviders` |

Capture **`deploymentId`** and **`deploymentRealm`** and reuse them on every call.

## Step 1: create the identity provider

```
createOidcIdp(deploymentId, deploymentRealm, issuerOrDiscoveryUrl, clientId, clientSecret,
              realm?, alias?, displayName?, defaultScopes?, trustEmail?, syncMode?)
```

The partner's app must already exist with a client ID/secret before this call — the
partner's IT team hands these over along with their issuer URL. Returns a
**`redirectUri`**; if the partner's registered callback is a wildcard (e.g.
`.../broker/*`) any alias works, otherwise the alias must be chosen to match whatever
they whitelisted before calling this.

`trustEmail: true` is usually right when the partner has already verified their staff's
addresses.

## Step 2: map claims onto the brokered user

Every claim the partner's token carries that should land on the Keycloak user needs its
own mapper call:

```
addIdpAttributeMapper(deploymentId, deploymentRealm, idpAlias, protocol="oidc",
                       mapperName, source, userAttribute, realm?, syncMode?)
```

For the common shape (email/given_name/family_name → email/firstName/lastName), call it
three times — once per claim. `source` is the OIDC claim name the partner's ID token or
userinfo response actually sends (verify against their documentation rather than
assuming standard OIDC naming, especially for anything beyond these three).

## Step 3: verify by logging in as more than one user

Nothing here reports whether the button quietly grew an extra gate. The obvious
check — "a valid user with valid credentials gets in" — passes even on a
mis-scoped setup that also (incorrectly) blocks a different valid user, or that
happens to work only because the one test account is a member of some group. Drive at
least two real logins, with **two different partner accounts that are otherwise
unrelated to each other**, and confirm both land back at the application's redirect URI
with an authorization code — with no `account_hint` or organization-hint parameter on
the authorization request at all. If either user is rejected, something has been
over-scoped.

If scripting rather than clicking: Keycloak marks `AUTH_SESSION_ID` / `KC_RESTART` as
`Secure; SameSite=None`. A browser sends them over `http://localhost` anyway (loopback
is a secure context); most HTTP clients will not, so an auto-following redirect chain
silently loses the session and dead-ends at the broker endpoint. Follow redirects
manually and clear the flag after every response.

## Common errors

- **"Invalid redirect_uri"** — the `redirectUri` `createOidcIdp` returned isn't
  registered (or doesn't match a wildcard) on the partner's side.
- **A claim doesn't land on the user** — `source` in `addIdpAttributeMapper` doesn't
  match the exact claim name the partner's token sends; check their documentation
  rather than assuming standard OIDC naming.
- **One test user works but the task actually wanted "any valid account"** — resist the
  urge to add an `account_hint` / organization check "just in case"; only add it if the
  request actually asked for membership-based restriction or domain-based routing.
