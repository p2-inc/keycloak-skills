# keycloak-email-otp-login Verifier Rubric

- `task_success`: scored 1.0 only when every check below holds, 0.0 otherwise.
  - The browser flow in effect for `acme-portal` contains a REQUIRED `ext-email-otp` execution
    with an identifier step ahead of it at the same nesting level.
  - A registered address reaches the emailed-code form with no password field present.
  - A real email is captured for that address containing a numeric code, and the code completes
    the login with an authorization code and the original `state`.
  - An unregistered address reaches the identical form, receives no mail, and gets no account
    created - the realm must not reveal which addresses have accounts.
  - The seeded accounts still exist and are enabled, and exactly the `master` and `acme` realms
    exist (nothing else created or removed).
