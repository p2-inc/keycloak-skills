---
name: keycloak
description: >-
  Use when turning on passwordless login in Keycloak or Phase Two hosted Keycloak, either by
  emailed magic link (the real p2-inc `keycloak-magic-link` provider) or by passkey-only WebAuthn
  (no password field ever shown, no fallback). Use this whenever someone wants "passwordless
  login", "log in with a magic link", "email people a login link instead of a password", "sign in
  with a passkey/security key/Face ID/Touch ID and nothing else", or "remove password login
  entirely in favor of WebAuthn" — even if they only say "passwordless" or "passkeys". Covers the
  built-in "magic link" flow the provider auto-creates on every realm (no custom flow authoring
  needed, only binding it), the realm SMTP settings it depends on, the anti-enumeration behavior
  that makes registered and unregistered addresses look identical from the login page, and the
  create-user-if-none-exists setting that silently provisions an account for anyone's email unless
  turned off; and separately, the realm's WebAuthn PASSWORDLESS policy, authoring and binding a
  passkey-only flow (no MCP tool authors flows — documented REST recipe), and the credential-
  bootstrap problem for a user with zero credentials — driven via either raw Admin REST or the
  Keycloak MCP server. Not WebAuthn as a second factor alongside a password (a different, simpler
  policy — not covered here) and not a one-time code typed in (a sibling authenticator, not covered
  here). Not general Keycloak/Phase Two administration or plugin development — those aren't
  covered by this skill yet.
license: Apache-2.0
metadata:
  version: '0.5.0'
  author: Phase Two <support@phasetwo.io>
---

# Keycloak

Detect intent → detect tooling → load 1 reference file. If nothing matches, offer to file a gap
issue instead of guessing (see Step 1's "No intent matches").

This skill is a **router**. It contains no implementation or configuration steps itself — every
instruction lives behind a `Read:` in **Step 3**. Keep this file loaded; load references on demand.

---

## Step 1: Detect intent

| What the developer wants (plain language) | Intent |
|---|---|
| Turn on passwordless login by emailed link — "passwordless login", "log in with a magic link", "email people a login link instead of a password", "let users sign in without a password" (even just "passwordless" alone). Not WebAuthn/passkey passwordless (a different mechanism, see below) and not a one-time code typed in (a sibling authenticator, not covered here). | **admin:passwordless-magic-link** |
| Turn on passkey-only login — "passkey login", "no more passwords", "sign in with a passkey/security key/Face ID/Touch ID and nothing else", "remove password login entirely in favor of WebAuthn" (even just "passkeys" alone). Not WebAuthn as a second factor alongside a password (a different, simpler policy, not covered here) and not magic-link's email mechanism (no cryptographic ceremony involved). | **admin:passwordless-passkey** |

### No intent matches

Don't force an uncovered request into `admin:passwordless-magic-link` just to have somewhere to
send it — that produces confidently wrong guidance. If the request is genuinely something else
(plugin development, realm/client administration, IdP federation, or anything not in the table
above):

1. Say plainly that this isn't covered yet, and what you understood the request to be.
2. Ask if they'd like an issue opened in this repo (`p2-inc/agent-skills`) describing the gap —
   that's how this router grows new intents (see `references/README.md`'s "growing this router"
   note) instead of silently mis-routing.
3. If they say yes, draft the issue with:
   - **The verbatim prompt** — the developer's own request text, unedited, in a quoted block. This
     is the point of filing the issue at all: a paraphrase loses exactly the phrasing future router
     updates need to recognize this case. Never summarize it away.
   - Which intent(s) it was checked against and why nothing matched.
   - Anything else relevant already established in this conversation.

   Show the drafted issue to them before filing anything — opening an issue is a public, visible
   action and needs their explicit go-ahead on the actual content, not just on the idea of filing one.
4. If they decline, or if there's no way to open an issue (no `gh`/git remote access), just leave it
   there — don't paper over the gap by answering anyway.

---

## Step 2: Are you a Phase Two user?

This one question decides the **tooling** — ask it directly rather than trying to infer it from
context. Don't ask twice in the same conversation once it's established.

| Answer | Tooling |
|---|---|
| **Yes — Phase Two hosted Keycloak.** | **mcp.** If the `keycloak` MCP server isn't connected yet, prompt for it now: `mcp add --transport http keycloak https://mcp-staging.phasetwo.io/mcp`. If the developer declines, fall back to `rest` and say upfront what can't be verified as a result. |
| **No — self-managed Keycloak** (bare metal, Docker, Kubernetes; the developer has direct Admin REST access). | **rest.** |

If the answer is ambiguous, ask — don't guess and don't default to either side.

---

## Step 3: Load reference files

### admin:passwordless-magic-link
```
Read: references/admin-passwordless-magic-link-{tooling}.md
  tooling=mcp  → references/admin-passwordless-magic-link-mcp.md
  tooling=rest → references/admin-passwordless-magic-link.md
```

### admin:passwordless-passkey
```
Read: references/admin-passwordless-passkey-{tooling}.md
  tooling=mcp  → references/admin-passwordless-passkey-mcp.md
  tooling=rest → references/admin-passwordless-passkey.md
```
