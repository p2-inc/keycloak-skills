# GitHub (social login) — console walkthrough

`providerId=github`, driven by `createSocialIdp`.

## Steps, in order

1. **GitHub → Settings → Developer settings → OAuth Apps → New OAuth App** (for a personal account)
   or the equivalent under an **organization's** Developer settings if the app should belong to an
   org rather than a user.
2. Fill in **Application name** and **Homepage URL**.
3. Compute (or get from `createSocialIdp`'s return) the redirect URI:
   `{baseUrl}/realms/{deploymentRealm}/broker/{alias}/endpoint`, and paste it into
   **"Authorization callback URL."** GitHub allows only one callback URL per OAuth App (unlike some
   other vendors, there's no list to add to) — if the deployment's `alias` or base URL ever changes,
   this field has to be updated too.
4. **Generate a new client secret** — copy it immediately.
5. Copy the **Client ID** from the app's page.
6. Call `createSocialIdp(providerId="github", clientId=..., clientSecret=..., ...)`.

## Attribute mapping (Keycloak side)

GitHub's OAuth user-info response does **not** use OIDC-standard claim names — check the actual
response shape (`GET /user` via GitHub's API) rather than assuming `given_name`/`family_name` exist.
GitHub returns a single `name` field (often the full display name, not split first/last) and `login`
(the username) — map those, not the OIDC-standard mapper table from other providers.

Two things to get right, verified against Keycloak's own source
(`org.keycloak.social.github.GitHubUserAttributeMapper`, `org.keycloak.broker.oidc.mappers.UsernameTemplateMapper`):

- **Username from `login`**: Keycloak ships a purpose-built `github-user-attribute-mapper` for
  this provider — its config keys are `jsonField` (e.g. `login`) and `userAttribute`, not the
  generic `claim`/`user.attribute` pair `addIdpAttributeMapper` builds. The generic username
  mapper, `oidc-username-idp-mapper` (Username Template Importer), also works if pointed at
  `${CLAIM.login}` explicitly — its **factory default template is `${CLAIM.preferred_username}`,
  which GitHub never sends**, so leaving it at the default silently imports an empty username. Set
  the template explicitly; don't assume the default is safe just because the mapper was added.
- **`name`/`firstName` via `addIdpAttributeMapper`**: see `admin-social-login-mcp.md`'s "known tool
  bug" note — the tool's `oidc-user-attribute-mapper` string isn't a mapper Keycloak has registered
  for identity-provider brokering at all (that ID belongs to an unrelated SAML client protocol
  mapper); the correct one is `oidc-user-attribute-idp-mapper`. Confirm the mapper actually
  populates `firstName` after a real login rather than trusting a success response from creating it.

## Gotchas

- Only **one** callback URL per GitHub OAuth App — there's no multi-URL list like Google's.
- A private/verified email on the GitHub account may not appear in the default response unless the
  `user:email` scope is requested — pass it via `defaultScopes` if email is required for the mapper
  to have something to map.
- The client secret is shown once at creation — regenerate rather than trying to recover it.
