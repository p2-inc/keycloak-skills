# Social login (Google, Microsoft, GitHub, Facebook, ...) — via raw Admin REST

## What this is

A **built-in** identity provider — Keycloak ships the OAuth2 plumbing for a fixed set of consumer
providers, so setup is just a client ID + client secret from that provider's developer console. No
discovery URL, no metadata URL, no certificate. This is "Sign in with Google," not enterprise SSO —
if the ask is a company's own Entra ID/Okta/etc. tenant, that's `admin:idp-federation`, not this
intent.

## The built-in provider IDs

Confirmed against Keycloak's own `org.keycloak.social` package (one factory per row):

| `providerId` | Vendor |
|---|---|
| `google` | Google |
| `microsoft` | Microsoft **personal** accounts — see the Entra ID note below |
| `github` | GitHub |
| `gitlab` | GitLab |
| `facebook` | Facebook |
| `bitbucket` | Bitbucket |
| `instagram` | Instagram |
| `twitter` | X / Twitter |
| `linkedin-openid-connect` | LinkedIn — note the id; plain `linkedin` was retired |
| `stackoverflow` | Stack Overflow |
| `paypal` | PayPal |
| `openshift-v4` | OpenShift v4 |

## Create the identity provider

```bash
BASE=http://localhost:8080       # include the relative path if configured
REALM=myrealm
H="Authorization: Bearer $ADMIN_TOKEN"

curl -s -X POST "$BASE/admin/realms/$REALM/identity-provider/instances" \
  -H "$H" -H 'Content-Type: application/json' -d '{
    "alias": "google",
    "displayName": "Sign in with Google",
    "providerId": "google",
    "enabled": true,
    "trustEmail": false,
    "storeToken": false,
    "linkOnly": false,
    "config": {
      "clientId": "<client id from Google Cloud Console>",
      "clientSecret": "<client secret>",
      "syncMode": "IMPORT"
    }
  }'
```

`trustEmail` defaults to `false` on a hand-built representation like this — set it to `true`
explicitly if the provider's own email verification should be trusted (reasonable for Google/GitHub;
worth thinking about for anything else).

The **redirect (callback) URI** the provider needs is always:
```
{BASE}/realms/{REALM}/broker/{alias}/endpoint
```
Register it as an authorized redirect URI in that provider's developer console before testing — login
will fail with "invalid redirect_uri" until it is.

For the exact console click-path per vendor, see `references/idp/social-google.md`,
`social-microsoft.md`, `social-github.md`, `social-facebook.md`. For the rest of the table above,
the mechanism is identical (OAuth app → client ID/secret → redirect URI back); no dedicated
walkthrough is written yet.

## Provider-specific config keys

Some built-in providers accept extra `config` keys beyond client ID/secret, verified against each
factory's `*IdentityProviderConfig` class:

| Provider | Extra config key | What it does |
|---|---|---|
| `google` | `hostedDomain` | Restrict login to accounts in one Google Workspace domain |
| `google` | `offlineAccess`, `userIp` | Request a refresh token; embed the caller's IP in the auth request |
| `microsoft` | `tenantId` | Restrict to one Entra ID tenant instead of "any Microsoft account" |
| `facebook` | `fetchedFields` | Which Graph API fields to request beyond the default set |
| `stackoverflow` | `key` | Stack Exchange API key — `stackoverflow` doesn't work without it |
| `paypal` | `sandbox` | Target PayPal's sandbox environment instead of production |

Add these directly under `config` in the create call above (or `PUT` them into an existing instance
at `/admin/realms/{realm}/identity-provider/instances/{alias}` with the full representation —
Keycloak's admin API is a full-representation update, so `GET` the current instance first, edit
`config`, then `PUT` it back).

> **Microsoft work/school (Entra ID) tenants**: don't use `providerId=microsoft` for this even
> though `tenantId` exists — see `admin:idp-federation`'s OIDC path with the tenant discovery URL,
> a cleaner fit for a single-tenant corporate login than the personal-account social provider.

## Attribute mappers (optional)

```bash
curl -s -X POST "$BASE/admin/realms/$REALM/identity-provider/instances/$ALIAS/mappers" \
  -H "$H" -H 'Content-Type: application/json' -d '{
    "name": "email",
    "identityProviderAlias": "'"$ALIAS"'",
    "identityProviderMapper": "oidc-user-attribute-idp-mapper",
    "config": {
      "syncMode": "INHERIT",
      "claim": "email",
      "user.attribute": "email"
    }
  }'
```
Common claims: `email` → `email`, `given_name` → `firstName`, `family_name` → `lastName`. GitHub's
claim names differ from the OIDC-standard ones above — check a real token/userinfo response rather
than assuming.

## Verify

```bash
curl -s "$BASE/admin/realms/$REALM/identity-provider/instances" -H "$H" \
  | jq '.[] | {alias, providerId, enabled}'
```
Then open the realm's login page — the provider's button should appear, and clicking it should
bounce to the vendor and back with a new or linked account.

## Common errors

- **"Invalid redirect_uri" at the provider** — the callback URI above must be registered exactly
  (scheme, host, path) in that provider's OAuth app.
- **Login succeeds but expected fields are missing on the user** — the provider's claim names don't
  match the mapper's `claim`; check the provider's actual token/claims, don't assume OIDC-standard
  names hold for every vendor.
- **`stackoverflow` provider fails outright** — missing the `key` config value; it's not optional
  for this one provider.
