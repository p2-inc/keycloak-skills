# keycloak-password-email-otp-mfa Verifier Rubric

- `task_success`: scored 1.0 only when every check below holds, 0.0 otherwise.
  - The browser flow in effect for `acme-portal` contains a REQUIRED password step running before
    a REQUIRED `ext-email-otp` at the same nesting level.
  - A correct password reaches the emailed-code step, a real email is captured with a numeric
    code, and the code completes the login with an authorization code and the original `state`.
  - A **wrong** password produces no mail at all - the password must gate the send, not merely
    precede it.
  - An unknown username produces no mail.
  - The seeded accounts still exist and are enabled, and exactly the `master` and `acme` realms
    exist (nothing else created or removed).
