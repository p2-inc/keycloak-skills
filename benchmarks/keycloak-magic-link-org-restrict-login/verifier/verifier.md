---
document_version: "0.1"
verifier:
  name: keycloak-magic-link-org-restrict-login
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

The verifier reads no agent-produced files. It discovers whatever flow is actually bound to
`acme-portal` (client override or realm-wide, resolved the same way Keycloak itself resolves
it) and inspects its executions directly, rather than assuming a specific flow alias or
authoring path - any correctly-shaped custom flow passes, whether it was authored via
`importAuthenticationFlow`, a manual create-flow/add-execution sequence, or anything else
that produces the right runtime behavior.

Structural check, on the flow actually in effect: it must contain `ext-auth-username-auth-note`,
`ext-select-org`, and `ext-magic-form` as sibling executions (same nesting level) in that exact
relative order, all `REQUIRED`, with `ext-select-org` configured `match_by_org_name=true` - the
task fixes the literal `account_hint` value ("engineering") the application always sends, since
it never learns a server-generated organization ID, which pins the only valid solution shape.
The ORDER is what actually matters here, more than in the plain org-restrict-login task: putting
`ext-magic-form` before `ext-select-org` would still eventually reject a non-member's login, but
would send them a working magic-link email first - a correctness violation this task is
specifically designed to catch, not just an implementation-quality nitpick.

Behavioral check: three real headless browser logins are driven against `acme-portal`, each
submitting only an email address (no password, ever) on whatever form the flow's first step
renders:

- `priya` (seeded as a plain user with a verified email, membership added by the agent) with
  the correct `account_hint` for her organization - must reach Keycloak's stock
  "check your email" page, receive a real captured email containing an action-token link, and
  completing that link must return an authorization code.
- `morgan` (seeded the same way, but never added to the organization) with the correct
  `account_hint` for the organization he is NOT a member of - must be rejected, and critically,
  must receive **no captured mail at all**. This is the strongest, correct reading of "his link
  should just not work": the gate has to stop the send before it happens, not merely reject a
  link that was already sent.
- `priya` with an `account_hint` that matches no real organization - must also be rejected with
  no mail sent, proving the gate checks membership in the specific hinted organization, not
  merely "is a member of something" or "some account_hint was present".

Finally, exactly `master` and the target realm must exist - nothing else should have been
created or removed.

Both the structural and behavioral checks were validated against a real, working
implementation before being written into this verifier - not assumed from documentation. In
particular, the single-POST behavior (no separate redirect for the org check; success and
rejection are both visible only in which terminal page is reached) was confirmed by actually
driving these logins against a live container running the real p2-inc keycloak-orgs and
keycloak-magic-link extensions together.
