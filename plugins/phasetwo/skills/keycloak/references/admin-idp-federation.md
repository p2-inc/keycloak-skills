# Enterprise identity federation (Entra ID, Okta, Auth0, ADFS, ...) — via raw Admin REST

## What this is

Brokering a **company's own** identity provider into Keycloak — SP-initiated SAML 2.0 or OIDC — so
their staff/customers log in there instead of at a Keycloak password form. Every vendor tile in the
Phase Two IdP wizard maps to one of these two mechanisms (Okta has its own dedicated skill). If the
ask is a consumer "log in with Google/GitHub" button instead, that's `admin:social-login` — a
different, client-ID-only mechanism.

## Step 1: which vendor, which protocol

| Vendor | Protocol | Vendor click-path |
|---|---|---|
| Microsoft Entra ID / Azure AD | SAML (or OIDC via app registration) | `references/idp/entra-id.md` |
| Okta | OIDC + SAML | `settingOktaIdentityProvider` skill |
| Auth0 | OIDC or SAML | `references/idp/auth0.md` |
| ADFS | SAML | `references/idp/adfs.md` |
| AWS IAM Identity Center | SAML | `references/idp/aws.md` |
| Google Workspace | SAML (not the `google` social provider) | `references/idp/google-workspace.md` |
| CyberArk (Identity) | SAML | `references/idp/cyberark.md` |
| JumpCloud | SAML | `references/idp/jumpcloud.md` |
| OneLogin | SAML | `references/idp/onelogin.md` |
| Oracle (OCI IAM) | SAML | `references/idp/oracle.md` |
| PingOne | SAML | `references/idp/pingone.md` |
| Duo (SSO) | SAML | `references/idp/duo.md` |
| Salesforce | OIDC or SAML | `references/idp/salesforce.md` |
| LastPass | SAML | `references/idp/lastpass.md` |
| Cloudflare (Access) | SAML | `references/idp/cloudflare.md` |
| Any other OIDC/SAML 2.0 IdP | either | use its own discovery/metadata; no dedicated walkthrough |

## Step 2: work out Keycloak's SP values before touching the vendor console

For SAML, most vendors want Keycloak's Entity ID and ACS URL *before* handing back their own IdP
metadata. These are deterministic — no need to create the IdP first:

```
Entity ID   = {BASE}/realms/{REALM}
ACS URL     = {BASE}/realms/{REALM}/broker/{ALIAS}/endpoint
SP metadata = {BASE}/realms/{REALM}/broker/{ALIAS}/endpoint/descriptor
```

Pick `ALIAS` up front, compute these, and give them to the vendor console first for every vendor
**except JumpCloud**, whose wizard reverses the order (vendor-side paste first, metadata export
last) — follow `references/idp/jumpcloud.md` exactly.

## Step 3: create the SAML IdP

Prefer importing the vendor's metadata (URL or raw XML) so Keycloak parses entity ID, SSO URL, and
certificate itself:

```bash
BASE=http://localhost:8080
REALM=myrealm
H="Authorization: Bearer $ADMIN_TOKEN"

# Import config from the vendor's metadata URL (or POST raw XML as a file if the vendor only
# offers a downloaded file and you can read its contents locally)
curl -s -X POST "$BASE/admin/realms/$REALM/identity-provider/import-config" \
  -H "$H" -H 'Content-Type: application/json' \
  -d '{"providerId":"saml","fromUrl":"<vendor metadata URL>"}' > /tmp/idp-config.json

# Merge clientId/clientSecret if this were OIDC (not needed for SAML) and create the instance
curl -s -X POST "$BASE/admin/realms/$REALM/identity-provider/instances" \
  -H "$H" -H 'Content-Type: application/json' -d '{
    "alias": "<ALIAS>",
    "displayName": "<vendor name>",
    "providerId": "saml",
    "enabled": true,
    "trustEmail": true,
    "storeToken": false,
    "linkOnly": false,
    "config": <contents of /tmp/idp-config.json, plus:
      "postBindingAuthnRequest": "true",
      "postBindingResponse": "true",
      "postBindingLogout": "true",
      "principalType": "SUBJECT",
      "validateSignature": "true">
  }'
```

If no metadata URL exists (only a downloaded file), skip `import-config` and build `config` directly
from the file's contents: `idpEntityId` (the file's `EntityDescriptor/@entityID`), the SSO service
URL (`SingleSignOnService/@Location`), and `signingCertificate` (the base64 cert inside
`X509Certificate`, no PEM headers).

## Step 4: or create the OIDC IdP (Auth0/Salesforce OIDC path)

```bash
curl -s -X POST "$BASE/admin/realms/$REALM/identity-provider/import-config" \
  -H "$H" -H 'Content-Type: application/json' \
  -d '{"providerId":"oidc","fromUrl":"https://<tenant-or-domain>/.well-known/openid-configuration"}' \
  > /tmp/idp-config.json

curl -s -X POST "$BASE/admin/realms/$REALM/identity-provider/instances" \
  -H "$H" -H 'Content-Type: application/json' -d '{
    "alias": "<ALIAS>",
    "displayName": "<vendor name>",
    "providerId": "oidc",
    "enabled": true,
    "trustEmail": true,
    "storeToken": false,
    "linkOnly": false,
    "config": <contents of /tmp/idp-config.json, plus:
      "clientId": "<client id>",
      "clientSecret": "<client secret>",
      "clientAuthMethod": "client_secret_post",
      "defaultScope": "openid profile email",
      "syncMode": "IMPORT">
  }'
```

The vendor app must already exist with a client ID/secret before this call — unlike SAML's
Entity-ID-first ordering, the OIDC redirect URI (`{BASE}/realms/{REALM}/broker/{ALIAS}/endpoint`) is
handed to the vendor **after** the app exists, when you register it as the allowed callback URL.

## Step 5: attribute mappers

```bash
curl -s -X POST "$BASE/admin/realms/$REALM/identity-provider/instances/$ALIAS/mappers" \
  -H "$H" -H 'Content-Type: application/json' -d '{
    "name": "email",
    "identityProviderAlias": "'"$ALIAS"'",
    "identityProviderMapper": "saml-user-attribute-idp-mapper",
    "config": {"syncMode":"INHERIT", "attribute.name": "email", "user.attribute": "email"}
  }'
```
Use `oidc-user-attribute-idp-mapper` + `"claim"` instead of `saml-user-attribute-idp-mapper` +
`"attribute.name"` for the OIDC path. Each vendor's file in `references/idp/` states the exact
claim/attribute names it actually sends — several vendors emit non-standard names.

## Step 6: verify

```bash
curl -s "$BASE/admin/realms/$REALM/identity-provider/instances/$ALIAS" -H "$H" | jq '{alias, providerId, enabled}'
```
Then open the realm's login page. A first failed SAML login almost always means the Entity ID / ACS
URL pasted into the vendor console in Step 2 doesn't match what got created — diff them with a `GET`
on the instance.

## Common errors

- **SAML assertion rejected / signature validation failure** — Entity ID/ACS URL mismatch, or
  `signingCertificate` never made it into `config` (check `validateSignature` and the cert value).
- **"Invalid redirect_uri" (OIDC vendors)** — the redirect URI registered on the vendor side must
  exactly match `{BASE}/realms/{REALM}/broker/{ALIAS}/endpoint`.
- **Login button never appears** — `enabled` is `false`, or the wrong client's login page is being
  checked.
