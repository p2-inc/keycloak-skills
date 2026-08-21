---
document_version: "0.1"
verifier:
  name: keycloak-idp-initiated-sso
  default_strategy: deterministic
  strategies:
    deterministic:
      type: script
      command: ./test.sh
  rubric:
    combine: weighted_mean
    dimensions:
      task_success: {weight: 1.0, source: deterministic}
  outputs:
    reward_json: /logs/verifier/reward.json
    details_json: /logs/verifier/reward-details.json
    aggregate_policy:
      method: weighted_mean
      metrics:
        task_success: 1.0
---

## verifier intent

The verifier reads no agent-produced files. It fires real **portal tiles** at Keycloak: a
mock vendor (`mock_idp.py`) hand-builds an *unsolicited* SAML response — no `InResponseTo`,
which is what makes it a tile click rather than a reply to something the app started — and
POSTs it at the broker's IdP-initiated endpoint

```
POST {base}/realms/acme/broker/{alias}/endpoint/clients/{urlName}
SAMLResponse=<base64 of the raw XML>   # POST binding: base64 only, not deflated
RelayState=<optional>
```

then follows the redirect chain to see **where** and **how** the browser was finally
delivered — deliberately stopping before requesting anything off-host, since the two apps
(`:9999`, `:9998`) are not listening and where the browser was sent is the whole point.

It discovers rather than assumes: both `{urlName}` values are read back off the clients'
`saml_idp_initiated_sso_url_name` attributes, so any names the agent chose pass.

### Sanctioned simplification: signature validation is off

Both fixture identity providers ship with `validateSignature=false` and
`wantAssertionsSigned=false`, and the mock's assertion is **unsigned**. The sandbox is
`no-network` and there is no real Okta or Entra tenant, so there is no vendor key to sign
with. This is deliberate and documented in `task.md`, not an oversight. It is orthogonal to
everything asserted here — which client a tile resolves to, and in what delivery shape —
and the agent is told to leave the providers alone.

### What is asserted, in order of importance

1. **OIDC-target delivery shape (the trap).** A tile aimed at `acme-portal`'s `{urlName}`
   must be delivered as a **302/303 redirect (GET)** whose `Location` is the app's main
   page `http://localhost:9999/`, and explicitly **not** as an HTML auto-POST form. An
   agent that copies the SAML recipe — leaving `saml_assertion_consumer_url_post` or
   `adminUrl` set, or `saml.force.post.binding` true — fails here, and the failure message
   names whichever of those three POST-forcing settings it found set. This is the check the
   naive happy path ("a tile logs someone in") cannot make: Keycloak builds a SAML response
   for an OIDC client quite happily, and the SSO cookie is set either way.
2. **SAML-target delivery.** A tile aimed at `acme-reports`'s `{urlName}` must be delivered
   by POST binding to its ACS `http://localhost:9998/saml/acs`, carrying a `SAMLResponse`.
   POST is correct here — a SAML app can read it.
3. **RelayState cannot route.** A tile into `acme-portal` sent with
   `RelayState=acme-reports` must still land in `acme-portal`. This pins the documented
   behaviour: `SAMLEndpoint.handleLoginResponse` takes the clientId branch and never reads
   the inbound RelayState, and `samlIdpInitiatedSSO` passes `null` on.
4. **Protocol-check asymmetry.** `GET {base}/realms/acme/protocol/saml/clients/{portalUrlName}`
   — the direct, non-broker endpoint — must return **400** with **"Wrong client protocol."**
   in the body, while the broker path for that same `{urlName}` resolves and delivers. That
   asymmetry (`SamlService.idpInitiatedSSO` calls `isClientProtocolCorrect()`;
   `SAMLEndpoint.samlIdpInitiatedSSO` filters only on `ClientModel::isEnabled`) is the only
   reason an OIDC app can be a tile target at all.
5. **Both vendors.** Checks 1 and 2 are parametrized over both the Okta-flavoured mock
   (NameID format `emailAddress`, plain `email`/`firstName`/`lastName` attributes) and the
   Entra-flavoured one (NameID format `persistent`, `http://schemas.xmlsoap.org/...` claim
   namespaces) — proving the wiring is on the client and therefore not tied to one alias.
6. **Untouched fixture.** Both identity providers still exist, still `enabled`, still
   `providerId: "saml"`; exactly `master` and `acme` realms exist.

Which client the tile actually resolved to is confirmed independently of the URL: the
`<saml:Audience>` in the response Keycloak *delivered* is the target client's `clientId`,
so every positive check also asserts that audience.

### Negative control (verified during development)

On the **unconfigured** initial realm the tile POST fails: Keycloak returns **400** with
`Client not found.` (`SAMLEndpoint.samlIdpInitiatedSSO` → `Errors.CLIENT_NOT_FOUND`),
because no client carries a matching `saml_idp_initiated_sso_url_name`. Running the
verifier against a fresh, untouched container scores **reward 0** — the `{urlName}`
discovery fixtures fail outright with a message naming the missing attribute. This verifier
genuinely fails before the agent does anything.

It was also confirmed to fail for the *right* reason on a plausible wrong answer: with both
`{urlName}`s set but `acme-portal` left with a POST assertion-consumer URL (the SAML recipe
copied verbatim), checks 1 and 3 fail and the reward is 0, while checks 2, 4, 5 and 6 still
pass.
