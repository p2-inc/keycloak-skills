---
name: socialLoginMcp
description: >-
  Add a built-in "Sign in with GitHub" (or Google/Microsoft/Facebook/...) social identity provider
  to a Phase Two hosted Keycloak realm, driven entirely through the Keycloak MCP server's tools.
  Use this whenever someone wants a plain consumer social login button - not a company's own
  enterprise IdP (that is admin:idp-federation). Covers createSocialIdp, why GitHub's own claim
  shape (login/name) is NOT the OIDC-standard shape (preferred_username/given_name/family_name),
  and why the generic OIDC attribute mapper is the wrong mapper type for GitHub specifically.
---

# Social login (e.g. "Sign in with GitHub") — via the Keycloak MCP server

## What this is

A **built-in** identity provider — Keycloak ships the OAuth2 plumbing for a fixed set of consumer
providers, so setup is just a client ID + client secret from that provider's developer console.
No discovery URL, no metadata URL, no certificate. This is "Sign in with GitHub," not enterprise
SSO — if the ask is a company's own Entra ID/Okta/etc. tenant, that's a different intent.

## Tools this skill drives (Keycloak MCP server)

| Purpose | Tool |
|---|---|
| Create the social provider | `createSocialIdp` |
| Add a claim/attribute mapper | `addIdpAttributeMapper` |
| Verify | `listIdentityProviders` |

Call:

```
createSocialIdp(deploymentId, deploymentRealm, providerId="github", clientId, clientSecret,
                 realm?, alias?, displayName?, defaultScopes?, syncMode?)
```

- The tool hardcodes `trustEmail=true` — fine for GitHub.
- Returns a `redirectUri` — always `{baseUrl}/realms/{deploymentRealm}/broker/{alias}/endpoint`.
  This is the callback URI to hand back for registration on GitHub's side.

## The trap: GitHub's claims are not OIDC-standard names

`addIdpAttributeMapper`'s own description talks in terms of "the OIDC claim" a provider sends —
that phrasing describes a generic OIDC IdP, and it is easy to carry over the
`given_name`/`family_name`/`preferred_username` pattern you'd use for Google, Auth0, or a
corporate OIDC tenant straight onto GitHub. **Don't.** GitHub's OAuth `/user` response has exactly
three identity-relevant fields:

| GitHub sends | NOT this OIDC-standard name |
|---|---|
| `login` (the username) | not `preferred_username`, not `sub` |
| `name` (the whole display name, one field) | not `given_name` / `family_name` (no split exists) |
| `email` | (this one does happen to match) |

`addIdpAttributeMapper(idpAlias, protocol="oidc", mapperName, source, userAttribute, ...)` is built
on Keycloak's generic OIDC claim mapper (`oidc-user-attribute-idp-mapper`), which reads from the
claim name you give it — so mapping `source="name"` → `userAttribute="firstName"` works whether or
not the underlying mapper type is GitHub-specific, because GitHub's raw profile JSON really does
have a `name` field at that path. What will NOT work is mapping `source="given_name"` or
`source="preferred_username"` — those fields simply are not present in what GitHub sends, and the
mapper will resolve to nothing every time, silently, with no error.

There is no MCP tool call for username re-mapping (Keycloak's Username Template Importer isn't
exposed here) — GitHub's own provider already sets the imported username from `login`
automatically on every login, with no explicit mapper required. Don't add a mapper that assumes
`preferred_username` exists; it doesn't, and nothing needs setting for username to work anyway.

## Verify

Call `listIdentityProviders` and confirm the alias shows `enabled: true`. Never trust that
mappers work "because they were created" — check the actual field names against GitHub's real
`/user` response shape above, not a Google/Auth0 mental model.

## Common errors

- **"Login succeeds but firstName is blank"** — the mapper's `source` names a claim GitHub
  doesn't send (`given_name`). Use `name` instead.
- **Username import looks wrong** — GitHub's own provider sets it from `login` automatically;
  nothing to configure through this tool set for that.
