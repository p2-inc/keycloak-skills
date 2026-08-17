# `keycloak` router — reference manifest

The [`../SKILL.md`](../SKILL.md) router dispatches to the files below. Each is loaded **on demand**
for a specific intent + tooling, never all at once.

## How the router reaches each file

- **Step 1** picks an **intent** (today, `admin:passwordless-magic-link` or `admin:passwordless-passkey`).
- **Step 2** picks a **tooling** (`mcp` or `rest`).
- **Step 3** maps the intent + tooling to the `Read:` list below.

## Reference files

| File | Intent (tooling) | Status |
|---|---|---|
| `admin-passwordless-magic-link.md` | `admin:passwordless-magic-link` (tooling=`rest`) — turning on the p2-inc `keycloak-magic-link` provider's built-in flow via raw Admin REST: binding, realm SMTP config, the anti-enumeration behavior, and the create-user-if-none-exists trap | ✅ done |
| `admin-passwordless-magic-link-mcp.md` | `admin:passwordless-magic-link` (tooling=`mcp`) — same outcome, driven end-to-end through Keycloak MCP server tools (`setSmtpSettings`, `listFlowExecutions`, `setExecutionAuthenticatorConfig`, `bindRealmAuthenticationFlow`/`bindClientAuthenticationFlow`) | ✅ done |
| `admin-passwordless-passkey-mcp.md` | `admin:passwordless-passkey` (tooling=`mcp`) — passkey-only WebAuthn login: the realm's WebAuthn PASSWORDLESS policy (`setWebAuthnPasswordlessPolicy`), authoring and binding a passkey-only flow (no MCP tool authors flows — documented REST recipe), and the credential-bootstrap problem for a zero-credential user (`sendRequiredActionEmail`) | ✅ done |
| `admin-passwordless-passkey.md` | `admin:passwordless-passkey` (tooling=`rest`) — same outcome via raw Admin REST: realm-representation PUT for the WebAuthn PASSWORDLESS policy and SMTP, authoring/binding the flow, and `execute-actions-email` for credential bootstrap | ✅ done |

## Authoring conventions

- **Router carries no domain content.** Steps and values live in references, not `SKILL.md`.
- **One intent, multiple tooling files — not multiple skills.** `admin:passwordless-magic-link` has
  two reference files (`-mcp` and plain) because the *outcome* is identical and only the driving
  mechanism (MCP tools vs. raw REST) differs. Prefer this shape — one intent, a `{tooling}`-suffixed
  file per mechanism — over splitting into separate skills whenever a capability has more than one
  valid tooling path to the same result.
- **Confirm live MCP tool names before writing a new reference** — don't assume a tool exists on
  the Keycloak MCP server without checking what's actually exposed. `admin-passwordless-magic-link-mcp.md`
  calls out which tools (`setSmtpSettings`, `listFlowExecutions`, `setExecutionAuthenticatorConfig`)
  are recent additions specifically so a missing tool reads as a real gap, not a skill bug.
- **Growing this router**: every capability here so far is genuine, verified content — not
  speculative scaffolding. Each new capability (plugin development, realm provisioning, IdP
  federation, clients, organizations, ...) should only get a `Read:` entry once it's actually
  written and verified the same way, not stubbed out ahead of time.
- **Uncovered requests become issues, not guesses.** `SKILL.md`'s "No intent matches" section is the
  intended feedback loop for this list — when the router can't route something, it offers to file a
  gap issue in this repo instead of forcing the request through `admin:passwordless-magic-link`.
  Each such issue carries the developer's **verbatim prompt**, not a paraphrase — that's what makes
  the backlog usable: a new intent row's "plain language" column should be written from the actual
  phrasing developers used, not a guess at how they'd phrase it.
