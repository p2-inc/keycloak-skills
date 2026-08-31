<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# Enterprise identity federation (Entra ID, Okta, Auth0, ADFS, ...) — via the Keycloak MCP server

## What this is

Brokering a **company's own** identity provider into Keycloak — SP-initiated SAML 2.0 or OIDC — so
their staff/customers log in there instead of at a Keycloak password form. This is a Phase Two IdP
wizard-parity intent: every vendor tile in that wizard maps to one of two mechanisms below (plus
Okta, which has its own dedicated skill). If the ask is a consumer "log in with Google/GitHub"
button instead, that's `admin:social-login`, not this one — no client-ID-only shortcut exists for
these vendors.

## Tools this skill drives (Keycloak MCP server)

| Purpose | Tool |
|---|---|
| Identify caller / realm | `whoAmI` |
| Generic OIDC IdP | `createOidcIdp` |
| Generic SAML IdP | `createSamlIdp` |
| Okta (OIDC + SAML) | hand off to `settingOktaIdentityProvider` |
| Attribute mapping | `addIdpAttributeMapper` |
| Verify | `listIdentityProviders` |
| Cleanup / re-create | `deleteIdentityProvider` |

Capture **`deploymentId`** and **`deploymentRealm`** and reuse them on every call.

## Step 1: which vendor, which protocol

| Vendor | Protocol → tool | Vendor click-path |
|---|---|---|
| Microsoft Entra ID / Azure AD | SAML → `createSamlIdp` (OIDC also works — see `connectingIdentityProvider`'s Stage 4 OIDC path if the developer prefers app-registration OIDC over an enterprise-app SAML config) | `references/idp/entra-id.md` |
| Okta | OIDC + SAML | hand off to `settingOktaIdentityProvider` |
| Auth0 | OIDC or SAML → `createOidcIdp` / `createSamlIdp` | `references/idp/auth0.md` |
| ADFS | SAML → `createSamlIdp` | `references/idp/adfs.md` |
| AWS IAM Identity Center | SAML → `createSamlIdp` | `references/idp/aws.md` |
| Google Workspace | SAML → `createSamlIdp` (NOT the `google` social provider — that's the personal-account button, `admin:social-login`) | `references/idp/google-workspace.md` |
| CyberArk (Identity) | SAML → `createSamlIdp` | `references/idp/cyberark.md` |
| JumpCloud | SAML → `createSamlIdp` | `references/idp/jumpcloud.md` |
| OneLogin | SAML → `createSamlIdp` | `references/idp/onelogin.md` |
| Oracle (OCI IAM) | SAML → `createSamlIdp` | `references/idp/oracle.md` |
| PingOne | SAML → `createSamlIdp` | `references/idp/pingone.md` |
| Duo (SSO) | SAML → `createSamlIdp` | `references/idp/duo.md` |
| Salesforce | OIDC or SAML → `createOidcIdp` / `createSamlIdp` | `references/idp/salesforce.md` |
| LastPass | SAML → `createSamlIdp` | `references/idp/lastpass.md` |
| Cloudflare (Access) | SAML → `createSamlIdp` | `references/idp/cloudflare.md` |
| Any other OIDC or SAML 2.0 IdP | `createOidcIdp` / `createSamlIdp` | use the vendor's own discovery/metadata URL; no dedicated walkthrough |

If unsure between OIDC and SAML for a vendor offering both (Auth0, Salesforce), prefer OIDC unless
the developer specifically needs SAML (e.g. an existing SSO deployment already standardized on it).

## Step 2: work out Keycloak's SP values BEFORE touching the vendor console

For SAML, most vendors ask for Keycloak's **Entity ID** and **ACS URL** *before* they'll hand back
their own IdP metadata (Entra ID, AWS, Cloudflare, CyberArk, Oracle, PingOne, OneLogin, Salesforce
SAML all follow this order in the verified wizard walkthroughs). These values are **deterministic**
— you don't need to call `createSamlIdp` first to know them:

```
Entity ID (spEntityId)                = {baseUrl}/realms/{deploymentRealm}
ACS URL (assertionConsumerServiceUrl) = {baseUrl}/realms/{deploymentRealm}/broker/{alias}/endpoint
SP metadata URL (spMetadataUrl)       = {baseUrl}/realms/{deploymentRealm}/broker/{alias}/endpoint/descriptor
```

Pick the `alias` up front (ask the developer, or default per the vendor file), compute these three
URLs, and hand them to the developer to paste into the vendor console **first** — then come back and
call `createSamlIdp` once you have the vendor's metadata URL or file. (`{baseUrl}` is the deployment's
cluster host — read it off any earlier tool result for this deployment, e.g. a prior `createSamlIdp`/
`createOidcIdp` `redirectUri`, or ask the developer for the cluster's console URL if this is the
first IdP created in the session.)

**JumpCloud is the one exception** — its wizard has the vendor-side paste happen first and the
metadata export happen *last*, after the app is activated. Follow `references/idp/jumpcloud.md`'s
order exactly rather than assuming every vendor works the same way.

## Step 3: create the IdP in Keycloak

```
createSamlIdp(deploymentId, deploymentRealm, realm?, alias?, displayName?,
              metadataUrl?, idpEntityId?, singleSignOnServiceUrl?, signingCertificate?, syncMode?)
```
Prefer `metadataUrl` (or the vendor's downloaded metadata file's contents, if the vendor only offers
a file — see below) over the fallback explicit fields; Keycloak parses entity ID, SSO URL, and
certificate from it in one shot. Returns `spEntityId`, `assertionConsumerServiceUrl`, `spMetadataUrl`
— confirm they match what you computed and already gave the vendor in Step 2.

```
createOidcIdp(deploymentId, deploymentRealm, issuerOrDiscoveryUrl, clientId, clientSecret,
              realm?, alias?, displayName?, defaultScopes?, trustEmail?, syncMode?)
```
For Auth0/Salesforce OIDC: `issuerOrDiscoveryUrl` is `https://{tenant-or-domain}` — the tool appends
`/.well-known/openid-configuration`. Returns a **`redirectUri`**; give it to the developer to paste
into the vendor's "Allowed Callback URLs" (Auth0) or equivalent, which for the OIDC path happens
*after* Keycloak creates the IdP (the reverse of the SAML ordering above) — the vendor app must
already exist with a client ID/secret before `createOidcIdp` can be called at all.

**A downloaded metadata file, not a URL**: several vendors (Google Workspace, Oracle, PingOne,
LastPass, Auth0 SAML) hand back a metadata **file** rather than a URL. `createSamlIdp`'s `metadataUrl`
argument needs a URL Keycloak can fetch — if the developer only has a downloaded file and no way to
host it, fall back to the explicit fields (`idpEntityId`, `singleSignOnServiceUrl`,
`signingCertificate`) read out of that file's contents, or to `admin-idp-federation.md`'s REST
`import-config` call, which can be pointed at a local file path or its raw XML.

## Step 4: attribute mappers

Every vendor's console setup in Step 1's table includes its own attribute-mapping step (mapping its
claims/SAML attributes to `email`/`firstName`/`lastName`/username). Mirror the same target attributes
on the Keycloak side with `addIdpAttributeMapper` (`idpAlias`, `protocol` = `oidc` or `saml`,
`mapperName`, `source`, `userAttribute`) — the vendor file for each provider states the exact
claim/attribute names it sends, which frequently are **not** the OIDC-standard names (e.g. AWS SSO
sends `${user:subject}`-style SAML attribute names it defines itself).

**Known tool bug — verify before trusting a "success" response.** `addIdpAttributeMapper` submits
`identityProviderMapper: "oidc-user-attribute-mapper"` / `"saml-user-attribute-mapper"`. Neither
string matches a Keycloak-registered identity-provider mapper factory (the real ones, confirmed
against Keycloak's own `org.keycloak.broker.{oidc,saml}.mappers.UserAttributeMapper` classes, are
`oidc-user-attribute-idp-mapper` and `saml-user-attribute-idp-mapper` — the strings the tool sends
belong to an unrelated SAML *client protocol* mapper). Keycloak's create-mapper endpoint doesn't
validate the provider ID at creation time, so the tool call reports success while the mapper never
actually fires at login — the only symptom is an empty `firstName`/`lastName`/`email` on the
brokered user afterward. Verify a mapper actually populated a field after a real test login before
telling the developer attribute mapping is done; if it's still broken on the server in front of you,
either use the raw REST call in `admin-idp-federation.md`'s Step 5 directly (with the correct
`*-idp-mapper` id) or say so and file it as a phasetwo-mcp bug rather than reporting success.

## Step 5: verify

`listIdentityProviders`, confirm `enabled: true`. Open the deployment realm's login page — the
provider's button should appear, and clicking it should redirect to the vendor and back. For SAML,
a first failed attempt almost always means the Entity ID / ACS URL pasted into the vendor console in
Step 2 didn't match what `createSamlIdp` actually returned in Step 3 — diff them.

## Re-running / fixing

`listIdentityProviders` never returns secrets or the SAML signing certificate. To change either,
`deleteIdentityProvider` (by alias) and re-run `createSamlIdp`/`createOidcIdp` — there's no in-place
secret/certificate update through this tool set.

## Common errors

- **SAML assertion rejected / signature validation failure** — Entity ID or ACS URL mismatch between
  what was pasted into the vendor and what `createSamlIdp` returned, or the vendor's certificate
  didn't come through (check `signingCertificate` was actually set — `createSamlIdp` only sets
  `validateSignature=true` when a certificate is present, from either the metadata import or the
  explicit fallback field).
- **"Invalid redirect_uri" (OIDC vendors)** — the `redirectUri` `createOidcIdp` returned must be
  registered exactly in the vendor's app.
- **Everything looks right but the login button never appears** — `enabled` was left `false`, or the
  developer is looking at the wrong client's login page (an alias created realm-wide still needs the
  client's flow to actually use the realm's identity-provider list, which it does by default unless a
  custom flow overrides it).
