# Registering the app's OIDC client — via the Keycloak MCP server

## What this is

Every integration in this skill needs a Keycloak **client** to exist before the app can log anyone
in. This file covers both branches of Step 4: creating one, and widening one that already exists.

A *client* is the app authenticating **against** Keycloak. That is the opposite direction from an
*identity provider*, which federates an external login **into** Keycloak — if the request is "log in
with Okta/Google", it belongs to the `keycloak` skill, not here.

**This file is OIDC.** If the app speaks SAML 2.0, the client is created with `createSamlClient`
instead — it takes an SP entity ID and ACS URL, or the app's `spMetadataXml` directly, and returns
the IdP-side `idpEntityId`, `ssoServiceUrl` and `idpMetadataUrl` the app needs. Note there is **no
update tool for SAML clients**, unlike `updateOidcClient` below, so an existing SAML client that
needs a changed attribute has to go the REST read-merge-PUT route. The app-side half of a SAML
integration — SP library, assertion handling — is not covered by this skill in v1; see SKILL.md's
"The app speaks SAML" section.

## Tools this file drives (Keycloak MCP server)

| Purpose | Tool |
|---|---|
| Identify caller / realm | `whoAmI` |
| **Find out whether the client already exists** | `listClients` |
| Create it (new branch) | `createOidcClient` |
| Widen redirect URIs / web origins (existing branch) | `updateOidcClient` |
| Rotate a leaked or expiring secret | `rotateClientSecret`, then `getRotatedClientSecret` |
| Remove one you created by mistake | `deleteClient` |

Capture **`deploymentId`** and **`deploymentRealm`** (from `createClusterDeployment`, or from the
developer if the deployment already exists) and reuse them on every call. A Phase Two deployment
**is** a Keycloak realm — same name, one to one.

## Step 1: Decide the client type — from the app, not from preference

This is decided by Step 2's framework detection, and it is not a judgement call:

| App shape | `clientType` | Why |
|---|---|---|
| Browser SPA — React, Angular, Vue, vanilla | `public` | A browser bundle cannot keep a secret. Anyone can read it in devtools. Auth-code + **PKCE** instead. |
| Native mobile / desktop — Android, iOS, React Native | `public` | Same reason: the binary ships to the user's device. PKCE. |
| Server-side web app that renders pages — Next.js with Auth.js, Express with sessions | `confidential` | The secret lives on a server the user never sees. |
| Backend service calling APIs with no user present | `service-account` | Client-credentials grant. No login UI, no redirect URIs. |

**A resource server (`app:protect-api`) usually needs no client of its own.** It validates tokens
issued to *other* clients. Create one only if the API also calls other services on its own behalf
(then: `service-account`). Don't create a client just because the intent mentioned Keycloak.

## Step 2: Find out which branch you are on

**Do this before asking the developer anything.** `listClients` answers it directly:

```
listClients(deploymentId, deploymentRealm)
```

It returns each client's `clientId`, `publicClient` flag, protocol, and enabled state — but
**never secrets**. Cross-check against the app's own config (`.env`, `keycloak.json`,
`application.properties`, `app.config.js`): a `clientId` already sitting there means the client
exists and its value is the answer.

Only ask outright when this is genuinely ambiguous.

## Step 3a: New client

```
createOidcClient(
  deploymentId, deploymentRealm,
  clientId      = "my-web-app",        # ask the developer; unique within the realm
  clientType    = "public",            # from the table above
  redirectUris  = "https://app.example.com/callback, http://localhost:3000/callback",
  webOrigins    = "https://app.example.com, http://localhost:3000",
  name          = "My Web App"         # optional, shown in the admin console
)
```

**Never invent `clientId` or `redirectUris`.** They are the developer's; ask for each and wait for
the answer. Ask for the local-development URI at the same time as the production one — coming back
to add it later is the single most common reason to need the "existing" branch an hour later.

The call returns:

| Field | What to do with it |
|---|---|
| `issuer` | Goes into the app's OIDC config. |
| `wellKnownUrl` | Better: point the library at this and it discovers every endpoint itself. |
| `clientSecret` | **Confidential and service-account only.** Show it once, prominently. Tell the developer to store it server-side. |
| `clientType` | Confirm it matches what you intended. |

For a `public` client there is **no secret** — say so explicitly rather than leaving the developer
hunting for one. The app uses PKCE.

## Step 3b: Existing client

The common case: the client works in production and now needs `http://localhost:3000/callback` for
local development.

```
updateOidcClient(
  deploymentId, deploymentRealm,
  clientId     = "my-web-app",
  redirectUris = "https://app.example.com/callback, http://localhost:3000/callback",
  webOrigins   = "https://app.example.com, http://localhost:3000"
)
```

Three things about this call that are load-bearing:

- **Both lists REPLACE, they do not append.** Read the current values from `listClients` first and
  send the full intended list. Sending only the new URI silently drops production.
- **Omitted arguments are left unchanged.** The tool reads the client's current representation and
  merges, specifically because Keycloak's underlying PUT replaces the *whole* client — a naive
  partial update would wipe every setting you didn't send. Supply at least one of `redirectUris`,
  `webOrigins`, `enabled` or the call is refused.
- **Never `deleteClient` a live client to change an attribute.** It takes the client's secret,
  its role mappings, and every session with it.

## Step 4: Redirect URIs and web origins are different things

The single most common "it worked in testing and breaks in the browser" failure, and it is worth
stating to the developer explicitly rather than just setting both:

| | Authorizes | Fails when wrong |
|---|---|---|
| **Redirect URI** | where Keycloak may send the user **back** after login | immediately and loudly — `Invalid redirect_uri` on the Keycloak error page, before login |
| **Web origin** | the **CORS** origin the browser's token call may come from | late and quietly — login appears to succeed, then the token request fails CORS in the browser console |

A scripted or server-side test passes with a wrong `webOrigins` because nothing triggers CORS. Only
a real browser catches it. Set both.

Matching is **exact** — scheme, host, port, and path all count. `http://localhost:3000` and
`http://127.0.0.1:3000` are different origins. So are `https://app.example.com` and
`https://app.example.com/`.

`webOrigins = "+"` means "exactly the origins of the registered redirect URIs" and is a reasonable
default for a browser app whose redirect URIs are already correct.

## Rotating a secret

`rotateClientSecret` exists — **do not** delete and re-create a client to change its secret.

```
rotateClientSecret(deploymentId, deploymentRealm, clientId, confirm = true)
getRotatedClientSecret(deploymentId, deploymentRealm, clientId)   # the previous secret, during grace
```

- `confirm` must be explicitly `true`. Without a configured rotation grace period the old secret
  stops working **immediately** and every consumer still using it fails to authenticate — confirm
  with the developer that consumers can be updated before calling.
- It refuses on a **public** client, correctly: a public client has no secret to rotate.
- `getRotatedClientSecret(..., invalidate = true)` ends the grace period early. Only once every
  consumer is confirmed on the new secret.

## Verify

```
listClients(deploymentId, deploymentRealm)
```

Confirm the client is present, `enabled: true`, the right protocol, and `publicClient` matches the
intended type. `listClients` does not return secrets, so a secret can only be confirmed from the
`createOidcClient` output or `getRotatedClientSecret` — if the developer lost it, rotate rather than
re-create.

Then have them run a real login in a real browser and watch for the two failures above.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `redirectUris is required` | a `confidential` or `public` client needs at least one | ask the developer for it; only `service-account` may omit it |
| `Invalid redirect_uri` on the Keycloak page | the URI the app sends doesn't exactly match a registered one | compare scheme/host/port/path character by character; check the app isn't appending a trailing slash |
| Login succeeds, then a CORS error on the token call | `webOrigins` missing or wrong | `updateOidcClient` with the correct origin, or `"+"` |
| `no client with clientId 'X'` | the argument is the internal UUID, not the `clientId` | use the human-readable `clientId`; `listClients` shows both |
| `rotateClientSecret refused: confirm must be true` | guard against breaking live consumers | confirm with the developer, then retry with `confirm = true` |
| Tools unavailable / not listed | usually an unauthorized OAuth connection, not a missing server | have the developer check `/mcp` |
