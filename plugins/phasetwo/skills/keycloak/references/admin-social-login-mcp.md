<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# Social login (Google, Microsoft, GitHub, Facebook, ...) — via the Keycloak MCP server

## What this is

A **built-in** identity provider — Keycloak ships the OAuth2/OIDC plumbing for a fixed set of
consumer providers, so setup is just a client ID + client secret from that provider's developer
console. No discovery URL, no metadata URL, no certificate. This is the "Sign in with Google"
button, not enterprise SSO — if the ask is a company's own Entra ID/Okta/etc. tenant, that's
`admin:idp-federation`, not this intent.

## Tools this skill drives (Keycloak MCP server)

| Purpose | Tool |
|---|---|
| Identify caller / realm | `whoAmI` |
| Create the social provider | `createSocialIdp` |
| Attribute mapping | `addIdpAttributeMapper` |
| Verify | `listIdentityProviders` |
| Cleanup / re-create (e.g. to rotate a secret) | `deleteIdentityProvider` |

Capture **`deploymentId`** and **`deploymentRealm`** (from `createClusterDeployment`) and reuse them
on every call.

## The built-in provider IDs

Keycloak ships these `providerId` values out of the box (confirmed against Keycloak's own
`org.keycloak.social` package, one factory class per row):

| `providerId` | Vendor |
|---|---|
| `google` | Google |
| `microsoft` | Microsoft **personal** accounts (see the Entra ID note below) |
| `github` | GitHub |
| `gitlab` | GitLab |
| `facebook` | Facebook |
| `bitbucket` | Bitbucket |
| `instagram` | Instagram |
| `twitter` | X / Twitter |
| `linkedin-openid-connect` | LinkedIn (note the id — plain `linkedin` was retired) |
| `stackoverflow` | Stack Overflow |
| `paypal` | PayPal |
| `openshift-v4` | OpenShift v4 |

`createSocialIdp` does not validate `providerId` against this list before calling Keycloak — a typo
surfaces as a REST failure from `createInstance`, not a friendly "unknown provider" message. Confirm
the id against this table before calling.

## Call `createSocialIdp`

```
createSocialIdp(deploymentId, deploymentRealm, providerId, clientId, clientSecret,
                realm?, alias?, displayName?, defaultScopes?, syncMode?)
```

- `alias` defaults to `providerId`; `displayName` defaults to `providerId` too — set both explicitly
  if the user wants a nicer login-button label (e.g. `displayName="Sign in with Google"`).
- The tool **hardcodes `trustEmail=true`** on every social IdP it creates — Keycloak's own default
  for a manually-created identity provider is untrusted email. This is a deliberate choice baked
  into the tool, not something you're asked about; mention it if the user cares whether a brokered
  account auto-verifies its email (it will).
- Returns a **`redirectUri`** — always `{baseUrl}/realms/{deploymentRealm}/broker/{alias}/endpoint`.
  Give this to the user to register as the **authorized redirect URI** in that provider's developer
  console. Nothing works until that's registered on the vendor side.

For the exact console click-path per vendor (where to create the OAuth app, which fields it wants,
where the redirect URI goes), see the matching file under `references/idp/`:
`references/idp/social-google.md`, `social-microsoft.md`, `social-github.md`, `social-facebook.md`.
For the remaining built-in providers (GitLab, Bitbucket, Instagram, X/Twitter, LinkedIn, Stack
Overflow, PayPal, OpenShift), there is no dedicated walkthrough yet — the mechanism is identical
(register an OAuth app on that vendor, get a client ID/secret, register the redirect URI back), so
proceed the same way and note plainly that the click-path hasn't been separately verified.

## Known gaps — provider-specific config `createSocialIdp` can't set

Several built-in providers accept extra config keys beyond client ID/secret, verified against each
factory's `*IdentityProviderConfig` class in Keycloak's source. None of these are exposed as
`createSocialIdp` arguments:

| Provider | Extra config key | What it does |
|---|---|---|
| `google` | `hostedDomain` | Restrict login to accounts in one Google Workspace domain |
| `google` | `offlineAccess`, `userIp` | Request a refresh token; embed the caller's IP in the auth request |
| `microsoft` | `tenantId` | Restrict to one Entra ID tenant instead of "any Microsoft account" |
| `facebook` | `fetchedFields` | Which Graph API fields to request beyond the default set |
| `stackoverflow` | `key` | Stack Exchange API key (required for `stackoverflow` to work at all) |
| `paypal` | `sandbox` | Target PayPal's sandbox environment instead of production |

If the user needs one of these, `createSocialIdp` cannot set it — say so, then either:
1. Point them at the deployment's admin console (Identity Providers → the alias → Settings) to add
   the extra config field by hand, or
2. If they have direct Admin REST access to the deployment, note the equivalent is a `PUT` to
   `/admin/realms/{realm}/identity-provider/instances/{alias}` merging the extra key into `config`
   (see `admin-social-login.md`'s REST steps for the exact shape) — but drive the *creation* itself
   through `createSocialIdp` first rather than hand-rolling the whole thing over REST.

Don't silently drop the request or fabricate a workaround — this is a real, documented tool
limitation, not a skill gap.

> **Microsoft work/school (Entra ID) tenants**: don't use `providerId=microsoft` for this — it's the
> personal-Microsoft-account provider and (per the gap above) its `tenantId` can't even be set
> through this tool. Use `admin:idp-federation`'s OIDC path with the tenant discovery URL instead.

## Attribute mappers (optional) — known tool bug, verify before trusting this

Add mappers with `addIdpAttributeMapper` (`idpAlias`, `protocol="oidc"`, `mapperName`, `source` — the
OIDC claim the provider sends — and `userAttribute`). Common: `email` → `email`, `given_name` →
`firstName`, `family_name` → `lastName`.

**As of this writing, `addIdpAttributeMapper` submits the wrong mapper provider ID and the mapper
silently never fires.** Verified against Keycloak's own registered broker-mapper factories
(`org.keycloak.broker.oidc.mappers.UserAttributeMapper`, `org.keycloak.broker.saml.mappers.UserAttributeMapper`):
the real IDs are `oidc-user-attribute-idp-mapper` and `saml-user-attribute-idp-mapper`. The tool
instead sends `oidc-user-attribute-mapper` / `saml-user-attribute-mapper` — **strings with no
matching registered factory at all** (those exact strings are only used by unrelated SAML
*protocol* mappers on clients, not identity-provider mappers). Keycloak's create-mapper endpoint
does not validate the provider ID at creation time, so the call reports success — the failure is
silent and only shows up as an empty `firstName`/`lastName`/`email` on the brokered user after a
real login. Confirm which behavior the server in front of you exhibits (check the mapper actually
populates a field after a real login) before trusting `addIdpAttributeMapper`'s success response;
if it's still broken, tell the developer plainly and either use the raw REST call in
`admin-social-login.md`'s attribute-mapper section directly (with the correct `*-idp-mapper` id) or
file it as a phasetwo-mcp bug rather than reporting the mapping as done.

GitHub sends different claim names than the OIDC-standard ones above (a single `name` field, not
`given_name`/`family_name`; `login`, not `preferred_username`, for the username) — check
`listIdentityProviders`/a test login's claims before assuming `given_name` exists, independent of
the mapper-ID bug above. See `references/idp/social-github.md`.

## Verify

Call `listIdentityProviders` and confirm the alias shows `enabled: true`. Then have the user open the
realm's login page (or any client's login page) — the provider's button should appear, and clicking
it should bounce to the vendor and back with a new or linked account.

## Re-running / fixing

`listIdentityProviders` never returns secrets. To rotate a client secret, `deleteIdentityProvider`
(by alias) and re-run `createSocialIdp` — there's no in-place secret update through this tool set.

## Common errors

- **"Invalid redirect_uri" at the provider** — the `redirectUri` `createSocialIdp` returned must be
  registered exactly (scheme, host, path) in that provider's OAuth app.
- **Login succeeds but expected fields are missing on the user** — the provider's claim names don't
  match what `addIdpAttributeMapper`'s `source` expects; check the provider's actual token/claims.
- **"I need to restrict this to our company's Google Workspace domain / Microsoft tenant"** — see
  "Known gaps" above; this isn't a `createSocialIdp` argument.
