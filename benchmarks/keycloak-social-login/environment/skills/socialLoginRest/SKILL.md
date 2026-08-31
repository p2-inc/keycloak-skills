---
name: socialLoginRest
description: >-
  Add a built-in "Sign in with GitHub" (or Google/Microsoft/Facebook/...) social identity provider
  to a Keycloak realm via raw Admin REST calls. Use this whenever someone wants a plain consumer
  social login button - not a company's own enterprise IdP. Covers POST
  /identity-provider/instances with providerId=github, why GitHub's own claim shape (login/name)
  is NOT the OIDC-standard shape (preferred_username/given_name/family_name), and the two mapper
  types GitHub actually needs (oidc-username-idp-mapper for username, github-user-attribute-mapper
  for everything else) rather than the generic oidc-user-attribute-idp-mapper.
---

<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# Social login (e.g. "Sign in with GitHub") — via raw Admin REST

## What this is

A **built-in** identity provider — Keycloak ships the OAuth2 plumbing for a fixed set of consumer
providers, so setup is just a client ID + client secret from that provider's developer console.
No discovery URL, no metadata URL, no certificate.

## Create the identity provider

```bash
BASE=http://localhost:8080/auth
REALM=acme
H="Authorization: Bearer $ADMIN_TOKEN"

curl -s -X POST "$BASE/admin/realms/$REALM/identity-provider/instances" \
  -H "$H" -H 'Content-Type: application/json' -d '{
    "alias": "github",
    "displayName": "GitHub",
    "providerId": "github",
    "enabled": true,
    "trustEmail": true,
    "storeToken": false,
    "linkOnly": false,
    "config": {
      "clientId": "<client id from the GitHub OAuth App>",
      "clientSecret": "<client secret>",
      "syncMode": "IMPORT"
    }
  }'
```

The redirect (callback) URI to register on GitHub's side is always:
```
{BASE}/realms/{REALM}/broker/{alias}/endpoint
```

## The trap: GitHub's claims are not OIDC-standard names

It's tempting to reach for the same mapper shape used for Google/Auth0/a corporate OIDC tenant:
`oidc-user-attribute-idp-mapper` with `claim`/`user.attribute` config keys, mapping
`given_name`→`firstName`, `family_name`→`lastName`, `preferred_username`→username. **None of that
holds for GitHub.** GitHub's OAuth `/user` response
(`org.keycloak.social.github.GitHubIdentityProvider.extractIdentityFromProfile` in Keycloak's own
source reads exactly these three fields, nothing else) has:

| GitHub sends | NOT this OIDC-standard name |
|---|---|
| `login` (the username) | not `preferred_username`, not `sub` |
| `name` (the whole display name, one field) | not `given_name` / `family_name` — no split exists |
| `email` | (matches) |

**GitHub's own compatible attribute mapper type is `github-user-attribute-mapper`** — a subclass
of `AbstractJsonUserAttributeMapper`, NOT the generic OIDC claim mapper. Its config keys are also
different: `jsonField`/`userAttribute`, not `claim`/`user.attribute`.

```bash
curl -s -X POST "$BASE/admin/realms/$REALM/identity-provider/instances/github/mappers" \
  -H "$H" -H 'Content-Type: application/json' -d '{
    "name": "github-firstname",
    "identityProviderAlias": "github",
    "identityProviderMapper": "github-user-attribute-mapper",
    "config": {
      "syncMode": "INHERIT",
      "jsonField": "name",
      "userAttribute": "firstName"
    }
  }'
```

Using `oidc-user-attribute-idp-mapper` with `claim: "name"` for this same mapping will silently
do nothing — it is not even a compatible mapper type for the `github` provider.

### Username: don't leave the default template pointed at a claim GitHub never sends

GitHub's own provider already sets the imported username from `login` automatically on every
login — no mapper is strictly required. If you do add a **Username Template Importer**
(`oidc-username-idp-mapper`) to make that explicit, its factory-default template is
`${ALIAS}.${CLAIM.preferred_username}`. GitHub's profile JSON has **no** `preferred_username`
field — left at the default, the template resolves to an unresolved variable and Keycloak sets
an *empty* username. Point it at GitHub's real field instead:

```bash
curl -s -X POST "$BASE/admin/realms/$REALM/identity-provider/instances/github/mappers" \
  -H "$H" -H 'Content-Type: application/json' -d '{
    "name": "github-username",
    "identityProviderAlias": "github",
    "identityProviderMapper": "oidc-username-idp-mapper",
    "config": {
      "template": "${CLAIM.login}",
      "target": "LOCAL"
    }
  }'
```

## Verify

```bash
curl -s "$BASE/admin/realms/$REALM/identity-provider/instances" -H "$H" \
  | jq '.[] | {alias, providerId, enabled}'
curl -s "$BASE/admin/realms/$REALM/identity-provider/instances/github/mappers" -H "$H" \
  | jq '.[] | {identityProviderMapper, config}'
```
Check the actual mapper type and config keys against GitHub's real field names above — don't
assume a mapper "looks right" just because it was created without a REST error.

## Common errors

- **Mapper created successfully, but the target attribute stays empty** — `identityProviderMapper`
  or its config keys don't match GitHub's real shape (`github-user-attribute-mapper` +
  `jsonField`/`userAttribute`, not the generic OIDC pair) or the source field name is an
  OIDC-standard one GitHub doesn't send (`given_name`, `preferred_username`).
- **Username is blank after login** — a Username Template Importer was added with the default
  template still referencing `${CLAIM.preferred_username}`; change it to `${CLAIM.login}`.
