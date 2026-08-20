# keycloak-social-login Verifier Rubric

- `task_success`: the `acme` realm offers "Sign in with GitHub" as a built-in social identity
  provider, wired with the fixture OAuth App's client ID/secret, and correctly maps GitHub's
  actual claim shape onto the Keycloak user rather than an OIDC-standard shape GitHub doesn't
  send. Scored 1.0 only when every check below holds, 0.0 otherwise.
  - Exactly one identity provider with `providerId == "github"` exists on `acme`, and it is
    enabled.
  - Its `clientSecret` is never returned in plaintext by the Admin REST API.
  - Asking Keycloak's own authorization endpoint for a login with `kc_idp_hint` set to this
    provider's alias returns a redirect (302 or 303) to `https://github.com/login/oauth/authorize`
    carrying the fixture GitHub OAuth App's `client_id`.
  - The redirect (callback) URI is the standard, discoverable
    `{baseUrl}/realms/acme/broker/{alias}/endpoint` shape.
  - A `oidc-username-idp-mapper` (Username Template Importer) mapper exists whose template
    references GitHub's real `login` field (`${CLAIM.login}`), not an OIDC-standard claim
    (`preferred_username`, `given_name`, `sub`, `email`) GitHub never sends.
  - A `github-user-attribute-mapper` mapper exists — GitHub's own compatible mapper type, not
    the generic `oidc-user-attribute-idp-mapper` — mapping its `name` JSON field to the user's
    `firstName` attribute, not an OIDC-standard field (`given_name`, `first_name`).
  - Exactly the `master` and `acme` realms exist.

## Why there is no live-login check

Keycloak's built-in social identity providers point at hardcoded real vendor endpoints in
Keycloak's own Java source — e.g. `GitHubIdentityProvider.DEFAULT_AUTH_URL =
"https://github.com/login/oauth/authorize"`. Unlike generic OIDC/SAML providers, there is no
configuration knob that redirects `providerId="github"` at a local fake IdP instead. In a
`no-network` sandbox there is therefore no way to drive a real end-to-end GitHub login, and this
task deliberately does not attempt one (no second realm pretending to be "GitHub," no live OAuth
round-trip against `github.com`). This is a documented scope limitation, not an oversight — see
`verifier/verifier.md` and `task.md`'s `difficulty_explanation` for the same note.

The `kc_idp_hint` redirect check is the strongest substitute available without network access:
Keycloak builds that redirect (including the outbound `client_id`) entirely from the realm's own
local IdP configuration before any request to GitHub would actually be sent, so it proves the
provider is really wired up — not just present in an admin listing — without ever reaching
`github.com`.
