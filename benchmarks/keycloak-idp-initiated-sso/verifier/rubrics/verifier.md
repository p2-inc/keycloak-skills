# keycloak-idp-initiated-sso Verifier Rubric

- `task_success`: realm `acme` delivers **portal tiles** — unsolicited SAML responses from
  either already-federated partner provider — into two specific applications, each in the
  delivery shape that application can actually use. Scored 1.0 only when every check below
  holds, 0.0 otherwise.

  **Sanctioned simplification, stated up front so it is not mistaken for an oversight:**
  both fixture identity providers are configured `validateSignature=false` /
  `wantAssertionsSigned=false`, and the mock vendor the verifier uses POSTs an **unsigned**
  SAML response. There is no real Okta or Entra tenant and the sandbox is `no-network`, so
  there is no vendor key to sign with. Signature validation is orthogonal to everything
  scored here (which client a tile resolves to, and how the browser is delivered), and the
  agent is told to leave the providers alone.

  - **OIDC-target delivery shape** — a tile POSTed at
    `{base}/realms/acme/broker/{alias}/endpoint/clients/{portalUrlName}` results in a
    **302/303 redirect (GET)** whose `Location` is `acme-portal`'s main page
    `http://localhost:9999/`, and **not** an HTML auto-POST form. This is the decisive
    check: an agent that copies the SAML recipe still "logs someone in", but auto-POSTs a
    SAML form at a web app that cannot read a POST body. The failure message names
    whichever POST-forcing setting was found set —
    `saml_assertion_consumer_url_post`, `adminUrl` (Master SAML Processing URL), or
    `saml.force.post.binding`.
  - **SAML-target delivery** — a tile at `{reportsUrlName}` is delivered by POST binding to
    `http://localhost:9998/saml/acs` with a `SAMLResponse`. POST is correct for a SAML app.
  - **RelayState cannot route** — a tile into `acme-portal` sent with
    `RelayState=acme-reports` still lands in `acme-portal`. Routing is the `{urlName}` path
    segment only; Keycloak never reads the inbound RelayState on this path.
  - **Protocol-check asymmetry** — `GET /realms/acme/protocol/saml/clients/{portalUrlName}`
    returns 400 "Wrong client protocol." for the OIDC client, while the broker path for the
    same `{urlName}` resolves and delivers.
  - **Both vendors** — the positive checks are repeated with an Okta-flavoured mock (NameID
    `emailAddress`, plain attribute names) and an Entra-flavoured one (NameID `persistent`,
    `http://schemas.xmlsoap.org/...` claim namespaces), proving the wiring is on the client
    and not tied to one alias.
  - **Audience confirmation** — every positive check also decodes the response Keycloak
    *delivered* and asserts its `<saml:Audience>` is the intended client's `clientId`, so
    "which client did the user land in" is answered independently of the URL.
  - **Untouched fixture** — `okta-sso` and `entra-sso` both still exist, `enabled`, with
    `providerId: "saml"`; exactly the `master` and `acme` realms exist.

- **Negative control**: on the unconfigured initial realm the tile POST returns 400
  `Client not found.` (no client carries a matching `saml_idp_initiated_sso_url_name`), and
  the verifier scores 0. Verified during development, together with the wrong-answer case
  (both `{urlName}`s set but `acme-portal` left with a POST assertion-consumer URL), which
  also scores 0 and fails specifically on the delivery-shape and RelayState checks.
