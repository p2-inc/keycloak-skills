---
name: idpFederationLoginRest
description: >-
  Broker a partner company's own OIDC identity provider into a self-managed Keycloak
  realm as a plain "log in with <partner>" button, using the Admin REST API only (no
  MCP server involved). Use this whenever someone asks to "let our partner's staff log
  in with their own account", "add a login-with-X button", "federate a partner's
  identity provider", or "broker an external OIDC provider" - with NO organization
  membership requirement and NO domain-based auto-routing attached. Covers
  POST identity-provider/instances, mapping claims onto the brokered user with
  oidc-user-attribute-idp-mapper, and verifying with more than one real user so no
  hidden per-user gate slips in. Not admin:org-restrict-login /
  admin:idp-org-restrict-login (those gate on organization membership) and not
  admin:corporate-sso-login (that routes by email domain) - this is an unconditional
  login button, nothing more.
---

# Broker a partner's OIDC identity provider as a plain login button — via raw Admin REST

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

## Step 1: create the identity provider

```bash
BASE=http://localhost:8080/auth       # include the relative path if one is configured
H="Authorization: Bearer $ADMIN_TOKEN"
REALM=<realm>
ALIAS=<idp-alias>

curl -s -X POST "$BASE/admin/realms/$REALM/identity-provider/instances" -H "$H" \
  -H 'Content-Type: application/json' -d '{
    "alias": "'"$ALIAS"'", "displayName": "Log in with <partner>", "providerId": "oidc",
    "enabled": true, "trustEmail": true, "storeToken": false, "linkOnly": false,
    "config": {
      "clientId": "<client-id>", "clientSecret": "<client-secret>",
      "clientAuthMethod": "client_secret_post",
      "authorizationUrl": "<authorization-endpoint>", "tokenUrl": "<token-endpoint>",
      "userInfoUrl": "<userinfo-endpoint>", "jwksUrl": "<jwks-uri>", "issuer": "<issuer>",
      "defaultScope": "openid profile email", "syncMode": "IMPORT", "useJwksUrl": "true"
    }}'
```

Either construct `config` directly from what the partner's IT team handed over (as
above), or resolve the endpoints first with `POST .../identity-provider/import-config`
using `{"providerId":"oidc","fromUrl":"<issuer>/.well-known/openid-configuration"}` and
merge in `clientId`/`clientSecret` — both work; the direct-construction path has one
fewer round trip and no dependency on outbound discovery fetches succeeding.

The redirect URI Keycloak will use is `{BASE}/realms/{REALM}/broker/{ALIAS}/endpoint`.
If the partner's registered callback is a wildcard (e.g. `.../broker/*`) any alias
works; otherwise pick the alias to match whatever they whitelisted ahead of time.

## Step 2: map claims onto the brokered user

```bash
curl -s -X POST "$BASE/admin/realms/$REALM/identity-provider/instances/$ALIAS/mappers" \
  -H "$H" -H 'Content-Type: application/json' -d '{
    "name": "email",
    "identityProviderAlias": "'"$ALIAS"'",
    "identityProviderMapper": "oidc-user-attribute-idp-mapper",
    "config": {"syncMode":"INHERIT", "claim": "email", "user.attribute": "email"}
  }'
```

Repeat once per claim — for the common shape that's three calls:
`email`→`email`, `given_name`→`firstName`, `family_name`→`lastName`. Verify the exact
claim names against the partner's documentation rather than assuming standard OIDC
naming; several providers emit non-standard names for anything beyond `email`.

## Step 3: verify by logging in as more than one user

Nothing here reports whether the button quietly grew an extra gate. The obvious
check — "a valid user with valid credentials gets in" — passes even on a mis-scoped
setup that also (incorrectly) blocks a different valid user. Drive at least two real
logins, with **two different partner accounts that are otherwise unrelated to each
other**, forcing the provider with `kc_idp_hint` and with **no** `account_hint` or
organization-hint parameter anywhere on the request:

```
$BASE/realms/$REALM/protocol/openid-connect/auth
  ?client_id=<client>&response_type=code&scope=openid
  &redirect_uri=<redirect>&state=<state>&kc_idp_hint=$ALIAS
```

Both users must land back at the redirect URI with a `code`. If either is rejected,
something has been over-scoped.

If scripting: Keycloak marks `AUTH_SESSION_ID` / `KC_RESTART` as `Secure;
SameSite=None`. A browser sends them over `http://localhost` anyway (loopback is a
secure context); most HTTP clients will not, so an auto-following redirect chain
silently loses the session and dead-ends at `/broker/{alias}/login`. Follow redirects
manually and clear the flag after every response (`cookie.secure = False` in Python
`requests`).

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| "Invalid redirect_uri" | The registered redirect URI on the partner's side doesn't match `{BASE}/realms/{REALM}/broker/{ALIAS}/endpoint` (or its wildcard). |
| A claim doesn't land on the user | `claim` in the mapper config doesn't match the exact name the partner's token sends. |
| Redirect chain dead-ends at `/broker/{alias}/login` | `Secure` cookies not sent over http by the client. |
| One test user works but the task actually wanted "any valid account" | Resist the urge to add an `account_hint` / organization check "just in case" — only add it if the request actually asked for membership-based restriction or domain-based routing. |
