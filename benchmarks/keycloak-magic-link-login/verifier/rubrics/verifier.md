# keycloak-magic-link-login Verifier Rubric

- `task_success`: the `acme` realm lets existing staff log in with an emailed link instead
  of a password, and does not extend that ability to unregistered addresses. Scored 1.0
  only when every check below holds, 0.0 otherwise.
  - Submitting `priya@acme.example` or `marcus@acme.example` on the login page shows no
    password field, and the mail-capture server receives a message to that address
    containing an `action-token` link.
  - Opening that link, with nothing else entered, returns the browser to
    `http://localhost:9999/callback` carrying an authorization code, with the `state`
    the application sent returned unchanged.
  - Submitting an address belonging to no existing account gets the same page response
    (status code) as a registered one.
  - No mail is captured and no new account is created for that unregistered address.
  - `priya` and `marcus` both still exist and are enabled.
  - Exactly the `master` and `acme` realms exist.
