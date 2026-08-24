# Keycloak skills — categories and skill backlog

A survey of what Keycloak's own documentation covers, organised into **categories** of work, with a
list of **capability ideas** inside each. This is a planning document: nothing here is written or
verified yet, and per [`../plugins/phasetwo/skills/keycloak/references/README.md`](../plugins/phasetwo/skills/keycloak/references/README.md)'s
authoring conventions, **nothing here should be added to a router until it's genuinely written and
verified**. Ideas graduate into intents; they don't get stubbed in ahead of time.

**An idea here is not assumed to be a skill.** §3 sets out the test that decides, and §4.1/§4.2 sort
every idea into one of three outcomes: an existing MCP tool call, a proposed tool, or a written
chapter. Most are not chapters. Read those two tables first — the category sections from **A** onward
are the underlying survey the tables are derived from.

Each idea carries four short points:

- **What** — the capability, in one line.
- **Use when** — plain-language triggers a developer would actually type. For a chapter these become
  the Step 1 intent-table row; for an operation they belong in the tool's description instead.
- **Problem** — what goes wrong without guidance (usually: an agent picks the wrong component, or
  gets the order wrong, or doesn't know the feature exists). **This is the load-bearing field** — it
  is what §3's test reads to decide whether a tool can absorb the idea.
- **Case** — a concrete scenario.

Plus two tags, and on corrected entries an **Outcome** line:

- **Tooling** — which driving mechanism(s) the reference files would cover. `mcp` = Keycloak MCP
  server tools, `rest` = raw Admin REST, `cli` = `kc.sh`/`kcadm`/env vars, `code` = writing source,
  `k8s` = CR/Helm/container config, `framework` = per-framework app integration.
- **Deps** — `stock` (vanilla Keycloak), or a named p2-inc extension, or `p2-saas` (Phase Two
  control plane only).

---

## 1. Source survey

Investigated Keycloak **26.6.5** at `../../keycloak/`. The documentation is in **two** trees, not
one, and this matters for the category list:

| Tree | Guides | `.adoc` files | What it covers |
|---|---|---|---|
| `docs/documentation/` | `server_admin` | 194 | Realm/client/user/role admin, authentication, identity brokering, organizations, sessions, events, user federation, workflows (IGA), threat model, OID4VCI |
| | `authorization_services` | 52 | Fine-grained resource authorization, policies, permissions, UMA, protection API |
| | `server_development` | 31 | SPIs, providers, user storage, custom REST endpoints, action tokens, event listeners, vault |
| | `upgrading` / `release_notes` | 117 | Version migration, breaking changes |
| | `api_documentation` | 3 | Pointer to the generated Admin REST/Javadoc |
| `docs/guides/` | `high-availability` | 59 | Single-cluster and multi-cluster (cross-DC) blueprints, Aurora, Infinispan, sizing |
| | `securing-apps` | 50 | Client registration, OIDC/SAML app integration, token exchange, DPoP, **MCP authorization server** |
| | `server` | 30 | Install, configuration, hostname, TLS, DB, cache, proxy, logging, features, import/export, FIPS, update-compatibility |
| | `observability` | 26 | Metrics, tracing, health, Grafana dashboards, SLIs |
| | `getting-started` | 16 | Docker/Podman/Kube/OpenShift/zip quickstarts |
| | `ui-customization` | 9 | Themes (FreeMarker and React), localization, custom console |
| | `operator` | 7 | Kubernetes operator, realm import, rolling updates |
| | `migration` | 2 | Quarkus distribution migration |

The user's brief named `docs/documentation/` only. I surveyed `docs/guides/` as well because
roughly half of what a developer asks an agent to do about Keycloak — "run this in Kubernetes",
"put it behind our load balancer", "secure my Next.js app" — lives exclusively in that second tree.
Ignoring it would have produced a category list biased entirely toward realm administration.

Notable things in 26.6 worth building for, because they're recent enough that a model's training
data is unreliable on them:

- **Workflows** (`server_admin/topics/workflows/`, 13 files) — a whole IGA engine: JML automation,
  access reviews, scheduled de-provisioning. Brand new surface area.
- **Fine-grained admin permissions v2** (`admin-console-permissions/fine-grain-v2.adoc`) —
  policy-based admin delegation that *replaces* the old RBAC-only story, and introduces "delegated
  realm administrators" as a third admin type.
- **MCP authorization server** (`securing-apps/mcp-authz-server.adoc`) — Keycloak as the OAuth
  authorization server for MCP servers, with a compliance matrix across four MCP spec versions.
  Directly adjacent to what `phasetwo-mcp` itself is.
- **Standard token exchange** — now distinct from, and preferred over, legacy token exchange; the
  doc has a whole comparison section because the two are easy to conflate.
- **Update compatibility command** — scriptable rolling-vs-recreate decisions.
- **OID4VCI** verifiable-credential issuance — explicitly experimental, do not ship a skill that
  presents it as production-ready.
- **Transient sessions**, **DPoP**, **client secret rotation**, **OAuth 2.1 / FAPI compliance**.

---

## 2. What already exists

The `keycloak` router covers **13 intents**, spread across four of the categories below:
6 in **A** (authentication), 4 in **B** (brokering), 1 in **C** (organizations), and 2 in **N**
(Phase Two platform). Everything marked ✅ in the category tables is already done; those rows are
listed so the backlog reads as a complete map rather than a diff.

---

## 3. Structural assessment

### The current structure

```
plugins/phasetwo/skills/keycloak/
├── SKILL.md                       ← one router: intent table + tooling question + Read map
├── references/
│   ├── README.md                  ← reference manifest
│   ├── admin-<intent>.md          ← 24 flat files, `-mcp` suffix or bare for REST
│   └── idp/<vendor>.md            ← 18 vendor console click-paths (tooling-agnostic)
├── assets/*.partial-import.json   ← 9 flow definitions
└── scripts/browser_login.py
```

This is a good design and I'd keep its core ideas: a router that carries no domain content,
progressive disclosure to exactly one reference file, one intent with a `{tooling}`-suffixed file
per mechanism, and intent rows that state what they are *not*.

### Where it breaks at this scale

Three problems were raised for this draft. One doesn't survive checking against the live
tooling; one is real but was mis-stated as a Keycloak-taxonomy problem when it's a work-shape
problem; one stands as written.

**1. ~~The frontmatter `description` is a hard wall, and we're already against it.~~ — checked,
and it isn't.** Running `skillsaw lint .` against the shipped router today:

```
⚠ WARNING (agentskill-description): Description exceeds 1024 characters (1113)
Errors: 0    Grade: A
```

The description is **1113 characters right now** — already past the "994 of ~1024" this draft
opened with, and past the limit entirely — and it lints clean at grade A, because the rule is a
**warning**, not the hard wall the draft called it. The real, *error-eligible* budget problem the
same lint run surfaces is different and sharper:

```
⚠ WARNING (context-budget): Estimated 5,001 tokens exceeds skill warn limit of 3,000
```

The router is 67% over its context budget, and the cause is the **intent table**, not the
frontmatter — each row is a full paragraph of sibling-disambiguation prose. Splitting into more
skills copies that bloat into more files with more frontmatters; it doesn't shrink a single row.

The "132 ideas can't fit in 994 characters" arithmetic also assumes cost is linear per idea. It
isn't — the 13 shipped intents are expensive specifically because "magic link" / "email OTP" /
"passkey" / "0 password" are semantically crowded and must be disambiguated against each other line
by line. Ideas outside that neighborhood (LDAP federation, cluster provisioning) cost the
description almost nothing to add, because nothing nearby competes with them. And of the current
1113 characters, **37% is an explicit quoted-trigger-phrase list** and **16% is enumerating 19
IdP vendor names** — real slack that honest trimming hasn't touched yet.

`adding-a-skill.md` §1's rule — *"if adding it pushes the description past the limit even after
honest trimming, that's the router doing too many **unrelated** things — split it"* — is a
coherence heuristic, not a capacity law, and the word carrying the rule is *unrelated*. Thirteen
passwordless-and-brokering intents are tightly related; that reads as a coherent router over
budget, not a router that's outgrown itself. Converting this into a 14-way split also trades a
loud, CI-visible failure (a lint warning) for a silent one: sibling skills mis-selecting at
routing time, which is exactly the failure class this repo's benchmark suite exists to catch, and
whose blast radius nobody has measured.

**2. Several categories don't fit the intent + `{mcp|rest}` shape — because `{mcp|rest}` was never
a work-shape axis.** `adding-a-skill.md` §1 already carves out extension development on this
ground, and the same reasoning extends to server installation, Kubernetes deployment, theme
source, and app integration — but the common thread isn't "the tooling menu needs more options,"
it's that **`mcp` vs `rest` is an access question, not a work-shape question**: both are just ways
of reaching a live realm. The categories this problem names aren't touching a live realm at all —
they're operating on the server process, on the developer's own application source, or on
Keycloak's own source. Once the cut is made on **target of the work** rather than on Keycloak's
documentation table of contents, this stops being five special cases needing five bespoke tooling
menus and becomes one rule with four outcomes — see the next section.

**3. The `admin-` prefix and flat namespace carry no information.**
24 files all starting `admin-` in one directory, already with two exceptions (`cluster-*-mcp.md`).
At 200+ reference files this is unnavigable.

### The decisive question: does this need a skill at all?

The three problems above are real, but the layout they imply — one router per category — answers the
wrong question. It assumes all 132 ideas are skills and asks how to arrange them. Most are not.

Checked against the live tooling: **`phasetwo-mcp` already exposes 99 tools**, and its REST client
layer is wired further still (`PUT /admin/realms/{realm}` and `PUT /clients/{id}` are both present,
so every realm-level setting is reachable today and merely lacks a `@Tool`). Around **15 of the ideas
below are already a single existing tool call**, and another **~55 are one call that nobody has
annotated yet**. Two of this document's own headline gaps are wrong on the facts — see the
corrections at **B5** and **J9/N3**.

That matters because of what this repo has already measured
(`docs/skill-building-lessons.md` §2–§3):

| Measurement | Result |
|---|---|
| No-skill baseline, both benchmarked tasks | **reward 1.0** — skills cut cost, they don't add capability |
| With-skill (MCP arm) vs no-skill | 33 calls / $0.85 vs 126 calls / $5.59 |
| With-skill (**REST-prose** arm) vs no-skill | **135 calls vs 126 — bought nothing** |
| Fixing one tool's swallowed error body | −51% calls, −79% cost, 6 → 0 errored calls |

The measured win came from routing to good tools, not from prose. Where the underlying path is
inherently many REST calls, prose guidance was indistinguishable from no guidance at all. So the
split to make first is not router-per-category — it is **operation vs. flow**:

- **Operations** — one call, or *n* calls with no decision in them — get an **MCP tool**, with the
  direct Admin REST call documented as a fallback. No prose. §4.2.
- **Flows** — where the wrong configuration succeeds silently, the order is load-bearing, the right
  answer is partly a refusal, or the fix lives in a different layer than the symptom — get a written
  **chapter**. §4.1.

A capability qualifies as a chapter only if it can name a concrete failure a tool signature cannot
prevent. If a clearer tool name, a safe default, or a better description removes the trap, the fix
is the tool: *a skill that exists to warn about a tool's footgun is a bug report.* **B5** is the
worked example — its two cited traps are already dead, killed by `createLdapUserStorage`'s
`READ_ONLY` default and its per-vendor attribute defaults.

### Proposed layout

**Four skills, not fourteen, not six.** A second pass folded the six-skill draft further once it
was checked against the same operation-vs-flow filter category by category: `keycloak-hardening`
and `keycloak-operations` share one target (the server process — whoever operates it doesn't care
whether the chapter is about a threat mitigation or a hostname flag), and `keycloak-theming`
mostly evaporates into a button (`setRealmThemes`) with three source-writing chapters left, which
belong next to extension development for the same reason — both write Java/FreeMarker/React source
against Keycloak's own codebase, not against a running realm.

What's left is one rule — **split where the target of the work changes** — with four outcomes:

| Target of the work | Skill | Routing axis | Chapters |
|---|---|---|---|
| a live realm | `keycloak` | `{mcp\|rest}` | 13 shipped + A8, A13, A14, B7, B8, F6, F10 |
| your own application's source | `securing-apps` | `{framework}` | H1–H14, plus G5 and H13 (planned separately) |
| the server process / its deployment | `keycloak-operations` | `{cli\|conf-file\|container}` | J1, J3, J4, J7, J9, J10, K9, G1, O1, O3, O6, H12 (O2, O4 as sections) |
| Keycloak's own source | `keycloak-extension-dev` | none | L1–L9, M2, M3, M4 |

Applying the filter to all 14 previously proposed category routers, not just the five already
called out as tool gaps: `keycloak-organizations`, `keycloak-users`, `keycloak-realm-ops` and
`phasetwo-platform` evaporate almost entirely (§4.2 already accounts for their content);
`keycloak-federation` merges into `keycloak`, since it's the same target and the same shipped
router; `keycloak-deployment` merges into `keycloak-server-config` (both target the server
process); `keycloak-theming` merges into `keycloak-extension-dev` (both target Keycloak's own
source); `keycloak-access-control` and `keycloak-clients` are almost entirely §4.2. Fourteen
categories inherited from how Red Hat organizes its documentation tree; four skills fall out of
how the work actually divides.

Retired as skills because tools absorb them: **A7, A9, A11, A12, A16, A18, B5, B6, C5–C8, D1–D5,
D9, E1, E2, E4, F1–F5, F7–F9, F11, G2, G3, G6, G8, I1–I6, I9, M1, M5, N3, N4** — plus the hosted
halves of **J6**, **J9** and **O5**.

This also settles problem 1 above without needing to be the reason for the split: four focused
descriptions discriminate at least as cleanly as six, the existing router's intent list still grows
by only **7** (absorbing B), and the description-length argument was never load-bearing to begin
with — see the correction above. What was load-bearing is problem 2's real form: target-of-work
mismatch. Problem 3 stands: reference files move into subdirectories, dropping the dead `admin-`
prefix.

```
keycloak/
├── SKILL.md
├── references/
│   ├── README.md
│   ├── passwordless/magic-link-mcp.md, ...
│   ├── brokering/corporate-sso.md, first-login-linking.md, federated-logout.md, ...
│   └── idp/<vendor>.md          ← unchanged, tooling-agnostic
└── assets/
```

`references/idp/` stays where it is. With brokering (**B**) and organizations (**C1**) folded into
the same `keycloak` skill rather than split across `keycloak-federation` and
`keycloak-organizations`, the cross-skill reference-sharing mechanism the six-skill draft still
needed (`plugins/phasetwo/shared/`, or a cross-skill `Read:`) is never required at all.

The tooling axis simplifies the same way. `{mcp|rest}` was never a work-shape question (see the
correction to problem 2) — under the MCP-first decision it collapses from a pair of parallel
`-mcp`/`-rest` files into one reference file with a fallback-REST column (§4.2's table format).
`{cli|conf-file|container}` in `keycloak-operations` isn't three branches either; it's three
spellings of one setting, stated inline in the chapter. Of the four skills, only `securing-apps`
keeps a real branching axis, because *which framework* actually changes which library and which
trap applies.

### Migration cost

Lower again than the six-skill estimate. The 13 existing intents all stay in the `keycloak` router
— no reshuffling — and reference files move only into subdirectories. `keycloak-operations` and
`keycloak-extension-dev` are new directories created when their first chapter is written, not up
front, and each now absorbs what would have been a second, thinner skill (`keycloak-hardening`,
`keycloak-theming`) rather than standing them up separately.

The real cost stays where it was: `phasetwo-mcp`, ~55 tools, staged in waves (§4.2). Most need only
a `@Tool` annotation and a DTO, since the REST calls are already wired. **This is still the plan's
main risk** — it is Java work in a different repo on a different release cycle, and if it is not
resourced those capabilities end up covered by nothing at all, which is worse than the original
draft's position of promising prose.

**Recommendation**: land Wave 1 tools and the two factual corrections (**B5**, **J9/N3**) before
writing any new reference file. The corrections are a live mis-route — `SKILL.md`'s frontmatter
still refuses LDAP/AD as having "no MCP tool," and five exist.

---

## 4. Categories and skill ideas

16 categories, 132 ideas — but they are not 132 skills. Sorted by §3's operation-vs-flow test:

| Outcome | Count | Where it goes |
|---|---|---|
| Already one existing MCP tool call | ~15 | §4.2 — close the idea |
| One call with no tool yet | ~55 | §4.2 — add the tool, write no prose |
| Genuine chapter | ~18 | §4.1 |
| Not an API-shaped task at all | ~28 | `securing-apps`, extension-dev, theming, deployment |
| Deferred as experimental or legacy (**P**) | 6 | §4 P |
| Already shipped as router intents (✅) | 13 | unchanged |

The category sections from **A** onward keep every idea and every **Problem** line — that analysis is
the valuable part and is what the two tables below are derived from. What changes is that an idea is
no longer assumed to be a skill.

### 4.1 Chapters — capabilities that need written guidance

Each row names a concrete failure that a tool signature cannot prevent. If that column can't be
filled, the row belongs in §4.2 instead.

| Chapter | Skill | Gate | Why a tool can't absorb it |
|---|---|---|---|
| A8 conditional MFA / step-up | `keycloak` | G3, G1 | `addConditional` exists; the nesting level is judgment, and a misplaced condition evaluates true silently — everyone gets prompted, or nobody does |
| A13 Kerberos / SPNEGO | `keycloak` | G5 | Spans authenticator, user federation and a server-side keytab; fails with opaque browser errors when any one is off |
| A14 X.509 / mutual TLS | `keycloak` | G5 | Half realm config, half `https-client-auth` server config |
| B7 first-login flow & account linking | `keycloak` | G4 | The correct answer is partly "not that way" — auto-linking by unverified email is an account-takeover vector |
| B8 federated logout & SLO | `keycloak` | G1 | Partial logout looks like success and is a security finding |
| F6 standard vs legacy token exchange | `keycloak` | G2, G4 | v2 is `DEFAULT` and v1 `PREVIEW` — the reverse of every older tutorial |
| F10 offline & transient sessions | `keycloak` | G2, G1 | Transient sessions are widely mis-stated as configurable; the only lever is a client switch that *disables* the optimization |
| G1 authorization-services vocabulary | `keycloak-operations` | G2 | Four concepts whose names each collide with something else in Keycloak; the CRUD beneath is a Wave 3 tool set |
| J1 first production configuration | `keycloak-operations` | G2 | The build-time vs runtime option split, plus `start-dev` in production |
| J3 truststore & outgoing TLS | `keycloak-operations` | G5 | `PKIX path building failed` is fixed in Keycloak's truststore, not the JVM's |
| J4 hostname & reverse proxy | `keycloak-operations` | G5 | Manifests as a token-validation 401, so the wrong layer gets debugged; reworked in v26, making pre-26 advice actively wrong |
| J7 feature flags | `keycloak-operations` | G2 | Which flags are default moved between 26.x releases |
| J9 extension install (self-managed) | `keycloak-operations` | G6 | The hosted half is a Wave 1 tool; `kc.sh build` + `providers/` is not an API |
| J10 bootstrap admin & recovery | `keycloak-operations` | — | Emergency procedure whose alternative is editing the database |
| K9 version upgrades | `keycloak-operations` | — | 117 files of upgrade notes; the work is finding the few changes that affect a given config |
| O1 security hardening checklist | `keycloak-operations` | G4 | 21 mitigations, individually easy, collectively never all applied |
| O3 OAuth 2.1 compliance | `keycloak-operations` | G4 | Prerequisite for H12 |
| O6 token & key compromise response | `keycloak-operations` | G4 | Composed from four mechanisms under time pressure, and must state plainly that a live access token cannot be un-issued |

Demoted to short sections or dropped — advice rather than mechanism, so no gate fires:
**C4** organizations vs `keycloak-orgs` (becomes a tool-description job, see §4.2 rule 7) ·
**E3** groups-vs-roles · **E5** master realm vs per-realm admin · **D10** GDPR posture ·
**H1** integration decision guide.

**H12** (Keycloak as an MCP authorization server) is a chapter in `keycloak-operations`, gated G5:
four MCP spec revisions with different mandatory standards, and the one capability here we can
verify against our own deployment.

### 4.2 Operations → MCP tool, with REST fallback

Every row is an operation, not a skill: one call, or *n* calls with no decision in them. The
fallback column is the direct Admin REST call — for self-managed Keycloak, and for use before a
proposed tool ships. Paths verified against the
[Admin REST API](https://www.keycloak.org/docs-api/latest/rest-api/index.html) and Phase Two's
control-plane OpenAPI.

#### Tool design — how a tool absorbs a would-be skill

These are the rules that make the column above legitimate rather than a way of dodging work. They
belong in `docs/skill-building-lessons.md` §3.

1. **Name the tool for the developer's question, not the endpoint.** `explainTokenClaims`, not
   `evaluateScopes`. F4's complaint is that Keycloak ships a scope evaluator "which nobody uses
   because they don't know it exists" — a tool named after the question is discoverable; prose
   pointing at a console feature is not.
2. **Encode the trap as a default, not a warning.** `editMode=READ_ONLY` is the model. A safe default
   applies when nobody read the paragraph.
3. **Split decoy siblings into distinctly-named tools.** Never one tool with a `mode` argument where
   the two modes *are* the classic confusion.
4. **Report resolved state, the way the target system resolves it.** Measured: a "what is bound?"
   tool that saw only realm level made a successful client-level write look like a failure, and the
   agent made 13 consecutive shell calls without returning to the tool surface.
5. **Return `nextStep` where order matters.** This is how a tool carries ordering knowledge that
   would otherwise have to be a chapter.
6. **Surface the upstream error body.** Already worth −51% calls / −79% cost once.
7. **Say what the tool is *not*.** The org tools drive Phase Two's `/realms/{realm}/orgs` API, not
   Keycloak's own `organizations` feature — which retires **C4**.

#### Already covered — close these ideas

| Idea | MCP tool | Fallback REST call |
|---|---|---|
| I2 SMTP | `setSmtpSettings` | `PUT /admin/realms/{realm}` → `smtpServer` |
| A11 password policy | `setPasswordPolicy` | `PUT /admin/realms/{realm}` → `passwordPolicy` |
| A12 brute force | `setBruteForceProtection`, `getUserLockoutStatus`, `clearUserLockout` | `PUT /admin/realms/{realm}`; `GET`/`DELETE /admin/realms/{realm}/attack-detection/brute-force/users/{id}` |
| D2 self-registration | `setLoginAndRegistrationSettings` | `PUT /admin/realms/{realm}` |
| A4 passkey policy | `getWebAuthnPasswordlessPolicy`, `setWebAuthnPasswordlessPolicy` | `PUT /admin/realms/{realm}` → `webAuthnPolicyPasswordless*` |
| F1 OIDC client | `createOidcClient` | `POST /admin/realms/{realm}/clients` |
| F2 SAML client | `createSamlClient` | `POST /admin/realms/{realm}/clients` |
| **B5 LDAP / Active Directory** | `createLdapUserStorage`, `testLdapConnection`, `syncLdapUsers`, `listUserStorageProviders`, `deleteUserStorageProvider` | `POST /admin/realms/{realm}/components`; `POST /admin/realms/{realm}/testLDAPConnection`; `POST /admin/realms/{realm}/user-storage/{id}/sync` |
| B6 IdP attribute mappers | `addIdpAttributeMapper` | `POST /admin/realms/{realm}/identity-provider/instances/{alias}/mappers` |
| C5, C8 organizations | 18 `OrgTools` plus the deployment-organization tools | `/realms/{realm}/orgs/*` |
| C7 per-organization IdP | `linkIdentityProviderToOrganization` | `POST /realms/{realm}/orgs/{orgId}/idps/link` |
| I4 event logging | `getEventSettings`, `enableRealmEvents` | `PUT /admin/realms/{realm}/events/config` |
| I5 event forwarding | `createWebhookSubscription`, `listWebhookSubscriptions`, `listWebhookDeliveryAttempts` | `POST`/`GET /realms/{realm}/webhooks`; `GET /realms/{realm}/webhooks/{id}/sends` |
| M1 theme branding | `listAvailableThemes`, `setRealmThemes`, `setClientLoginTheme` | `PUT /admin/realms/{realm}` |
| A18 flow debugging | `getAuthenticationBindings`, `listFlowExecutions`, `listAuthenticationFlows`, `clearClientAuthenticationFlowOverride` | `GET /admin/realms/{realm}`; `GET /admin/realms/{realm}/authentication/flows/{alias}/executions` |
| N4 cluster domain (part) | `updateClusterDomain`, `getClusterRestartStatus` | `PUT /realms/{realm}/clusters/{id}` |

#### Wave 1 — highest leverage

| Idea | Proposed tool | Fallback REST call |
|---|---|---|
| E1 realm & client roles | `listRealmRoles`, `createRealmRole`, `deleteRealmRole`, `addCompositeRole`, `grantUserRole`, `revokeUserRole`, `listUserEffectiveRoles` | `/admin/realms/{realm}/roles`; `/roles/{role-name}/composites`; `/users/{id}/role-mappings/realm` and `/realm/composite` |
| E2 groups & subgroups | `listGroups`, `createGroup`, `createSubGroup`, `addUserToGroup`, `listGroupMembers`, `setDefaultGroup` | `/admin/realms/{realm}/groups`; `/groups/{id}/children`; `PUT /users/{id}/groups/{group-id}`; `PUT /default-groups/{group-id}` |
| F4 client scopes & protocol mappers | `listClientScopes`, `createClientScope`, `addClientProtocolMapper`, `attachClientScopeToClient` | `/admin/realms/{realm}/client-scopes`; `/clients/{id}/protocol-mappers`; `PUT /clients/{id}/default-client-scopes/{scopeId}` and `/optional-client-scopes/{scopeId}` |
| **F4, E1, C6 — "why is my claim missing?"** | **`explainTokenClaims`**, `listEffectiveProtocolMappers`, `listGrantedRoleScopeMappings` | `GET /clients/{id}/evaluate-scopes/generate-example-access-token`; `/evaluate-scopes/protocol-mappers`; `/evaluate-scopes/scope-mappings/{roleContainerId}/granted` |
| D4 user CRUD & bulk ops | `createUser`, `updateUser`, `deleteUser`, `searchUsers`, `countUsers`, `setUserPassword` | `/admin/realms/{realm}/users` and `/users/{id}`; `/users/count` |
| F1 client update | `updateOidcClient` | `PUT /admin/realms/{realm}/clients/{id}` — already wired in the client layer, only the `@Tool` is missing |
| **J9, N3 — extensions** | `listClusterExtensions`, `installClusterExtension`, `removeClusterExtension`, `listSupportedKeycloakVersions` | `/realms/{realm}/clusters/{id}/extensions` and `/extensions/{extensionId}`; `GET /extensions/keycloak-versions`; `POST /extensions/cluster-update` |

`explainTokenClaims` is the highest-leverage single tool in this document: it answers what §F calls
"the highest-traffic troubleshooting topic in the whole product."

#### Wave 2 — session and lifecycle surface

| Idea | Proposed tool | Fallback REST call |
|---|---|---|
| A16, F5, F8 timeouts & lifespans | `setTokenAndSessionTimeouts` — one tool covering all five interacting values, its description stating that the shortest wins | `PUT /admin/realms/{realm}` |
| F9 logout & revocation | `listUserSessions`, `logoutUser`, `deleteSession`, `logoutAllSessions`, `pushClientRevocation` | `/users/{id}/sessions`; `POST /users/{id}/logout`; `DELETE /sessions/{session-id}`; `POST /logout-all`; `POST /clients/{id}/push-revocation` |
| D3 required actions & AIA | `listRequiredActions`, `enableRequiredAction`, `setDefaultRequiredAction`, `setRequiredActionConfig` | `/admin/realms/{realm}/authentication/required-actions` and `/{alias}`, `/{alias}/config` |
| D1 declarative user profile | `getUserProfileConfig`, `setUserProfileConfig` | `GET`/`PUT /admin/realms/{realm}/users/profile` |
| F7 client secret rotation | `rotateClientSecret` + `getRotatedClientSecret` — deliberately a pair, so the grace period is visible in the tool surface rather than buried in prose | `POST /clients/{id}/client-secret`; `GET`/`DELETE /clients/{id}/client-secret/rotated` |
| I3 realm keys | `listRealmKeys` | `GET /admin/realms/{realm}/keys` |
| I6, I7 import / export | `partialExportRealm`, `partialImportRealm` — the description must carry the auth-flow gap and point at `importAuthenticationFlow` | `POST /admin/realms/{realm}/partial-export`; `POST /admin/realms/{realm}/partial-import`; `POST /realms/{realm}/clusters/{id}/deployments/import` |
| D5 impersonation | `impersonateUser` | `POST /admin/realms/{realm}/users/{id}/impersonation` |
| N4, plus the hosted halves of J6 and O5 | `listClusterDomains`, `addClusterDomain`, `getClusterDomainStatus`, `setClusterEnvVar`, `listClusterIpRules`, `getClusterResourceUsage`, `getClusterLogs` | `/realms/{realm}/clusters/{id}/domains`, `/env-vars`, `/ip-rules`, `/resource`, `/logs` |

#### Wave 3 — deeper surfaces

| Idea | Proposed tool | Fallback REST call |
|---|---|---|
| G2, G3, G6, G8 authorization services | `enableResourceServer`, `createAuthzResource`, `createAuthzScope`, `createAuthzPolicy`, `createAuthzPermission`, **`evaluateAuthzPolicy`**, `importAuthzConfig` | `/clients/{id}/authz/resource-server` and `/resource`, `/scope`, `/policy`, `/permission`, `/import`; `POST /policy/evaluate` |
| A7 TOTP / authenticator-app MFA | `setOtpPolicy` | `PUT /admin/realms/{realm}` → `otpPolicy*` |
| A9 WebAuthn as a second factor | **`setWebAuthnTwoFactorPolicy`** — named distinctly to kill the passwordless-policy decoy | `PUT /admin/realms/{realm}` → `webAuthnPolicy*` |
| E4 fine-grained admin permissions v2 | `getClientManagementPermissions`, `setClientManagementPermissions` | `GET`/`PUT /clients/{id}/management/permissions` |
| B6 IdP role & claim mappers | `listIdpMappers`, `updateIdpMapper`, `deleteIdpMapper`, `addIdpRoleMapper` | `/identity-provider/instances/{alias}/mappers` and `/mappers/{mapper-id}` |
| LDAP mappers, key providers, SPI config | `listComponents`, `createComponent`, `updateComponent`, `listSubComponentTypes` | `/admin/realms/{realm}/components`, `/components/{id}`, `/components/{id}/sub-component-types` |
| I9, M5 localization | `setInternationalization` | `PUT /admin/realms/{realm}` → `internationalizationEnabled`, `supportedLocales` |

#### What a tool cannot absorb

Stated so the catalogue isn't over-claimed. A tool cannot **refuse** — B7's auto-link-by-unverified-
email is an account-takeover vector, and the guidance has to say so. It cannot **compose across
surfaces it doesn't own** — J4's hostname options are server configuration, not Admin REST. And it
cannot **choose** where judgment is the work — A8's conditional nesting level. Those are §4.1.

### A. Authentication & login flows

`server_admin/topics/authentication/*` (10 files), `login-settings/*`, `users/con-required-actions.adoc`,
`users/ref-user-credentials.adoc`. The most mature category — 6 of the 13 existing intents live here.

| # | Skill idea | Status |
|---|---|---|
| A1 | passwordless magic-link login | ✅ done |
| A2 | email OTP passwordless login | ✅ done |
| A3 | password + email OTP as MFA | ✅ done |
| A4 | passkey-only WebAuthn login | ✅ done |
| A5 | "0 password required" (passkey **or** magic link) | ✅ done |
| A6 | magic link restricted to an organization | ✅ done |

**A7 — TOTP/authenticator-app MFA**
- **What**: require an OTP from an authenticator app as a second factor; realm OTP policy (hash
  algorithm, digits, window, period) plus the `CONFIGURE_TOTP` required action.
- **Use when**: "add 2FA", "Google Authenticator", "require an authenticator app", "TOTP", "MFA
  with an app not email".
- **Problem**: the closest existing intent (A3) uses `ext-email-otp`, a p2-inc extension; an agent
  routed there will install a jar to do something stock Keycloak already does. Also the enrolment
  half (required action vs. conditional sub-flow) is where this usually gets botched.
- **Case**: an admin wants app-based 2FA for everyone in the realm, enforced on next login.
- **Tooling**: mcp, rest · **Deps**: stock

**A8 — Conditional MFA (step-up by role, group, or client)**
- **What**: `conditional-user-configured`, `conditional-user-role`, and LoA-based conditions inside
  a sub-flow, so a second factor is demanded only for some users or some clients.
- **Use when**: "only require 2FA for admins", "step-up authentication", "MFA for this app only",
  "require stronger auth for the payments client", "ACR/LoA".
- **Problem**: conditional sub-flows are the single most misunderstood construct in Keycloak
  authentication. A condition placed at the wrong nesting level silently evaluates to true, so
  everyone gets prompted — or nobody does, which is worse and invisible.
- **Case**: SaaS enforces 2FA for users holding `realm-admin` and leaves everyone else on password.
- **Tooling**: mcp, rest · **Deps**: stock

**A9 — WebAuthn as a second factor (not passwordless)**
- **What**: the `webauthn` (two-factor) authenticator plus the realm's WebAuthn *policy* — a
  different policy object from the PASSWORDLESS one A4 configures.
- **Use when**: "security key as 2FA", "YubiKey after password", "passkey *and* password".
- **Problem**: A4's reference explicitly scopes itself out of this, and the two realm policies are
  separate objects with near-identical field sets — configuring the wrong one produces a flow that
  looks right and never triggers.
- **Case**: a regulated customer requires a hardware key in addition to a password.
- **Tooling**: mcp, rest · **Deps**: stock

**A10 — Recovery codes**
- **What**: enable the recovery-codes credential and the required action, as a fallback when a
  user's second factor is lost.
- **Use when**: "backup codes", "what if they lose their phone", "2FA recovery", "account lockout
  fallback".
- **Problem**: teams turn on MFA and discover the recovery story only after the first support
  ticket. The credential type is only half of it — it does nothing until the required action is
  enabled and a conditional sub-flow offers it as an alternative to the primary second factor.
  Verified as `Type.DEFAULT` in 26.6 (`Profile.java`), but it was a preview feature in earlier
  releases, so version matters for whether it's visible at all.
- **Case**: rolling out A7 realm-wide and needing a self-service recovery path.
- **Tooling**: mcp, rest · **Deps**: stock

**A11 — Password policies**
- **What**: realm password policy — length, character classes, `notUsername`, password history,
  `maxAuthAge`, hashing algorithm and iterations.
- **Use when**: "enforce strong passwords", "password expiry", "NIST/PCI password requirements",
  "increase hashing iterations", "argon2".
- **Problem**: the hashing-algorithm and iteration settings have real performance consequences
  (and a rehash-on-login behaviour) that are easy to set badly; and the policy string format is
  a single concatenated field, not a structured object.
- **Case**: a compliance audit demands 12 characters, history of 5, and 90-day expiry.
- **Tooling**: mcp, rest · **Deps**: stock

**A12 — Brute-force detection and lockout**
- **What**: permanent vs. temporary lockout, wait increments, failure thresholds, the quick-login
  check, and the newer per-IP/per-user modes.
- **Use when**: "lock accounts after failed logins", "brute force", "rate limit login", "stop
  credential stuffing".
- **Problem**: already flagged as load-bearing in the existing A2 reference (a 6-digit code without
  brute-force protection is guessable), so it's a dependency of other skills, not just standalone.
  The permanent-lockout mode also creates a self-inflicted DoS if set without a recovery path.
- **Case**: a public login page is being credential-stuffed.
- **Tooling**: mcp, rest · **Deps**: stock

**A13 — Kerberos / SPNEGO desktop SSO**
- **What**: `kerberos` authenticator plus keytab configuration, optionally chained to LDAP user
  federation.
- **Use when**: "desktop SSO", "Windows integrated auth", "SPNEGO", "no login prompt on the
  corporate network", "Kerberos".
- **Problem**: it spans three separate config surfaces (authenticator, user federation provider,
  server-side keytab and JVM flags) and fails with opaque browser-level errors when any one is off.
- **Case**: an enterprise wants domain-joined machines signed in silently.
- **Tooling**: rest, cli · **Deps**: stock

**A14 — X.509 / mutual-TLS client certificate authentication**
- **What**: the X.509 browser and direct-grant authenticators, identity extraction and mapping to a
  user, plus the server-side mTLS listener config.
- **Use when**: "smart card login", "PIV/CAC", "client certificate authentication", "mTLS login".
- **Problem**: half of it is realm config and half is server config (`https-client-auth`), and the
  identity-extraction regex is the usual failure point.
- **Case**: a government customer authenticates staff with smart cards.
- **Tooling**: rest, cli · **Deps**: stock

**A15 — Forgot password / password reset flow**
- **What**: the reset-credentials flow, its email step, token lifespan, and the anti-enumeration
  behaviour.
- **Use when**: "forgot password email", "let users reset their own password", "password reset link
  expired".
- **Problem**: it needs realm SMTP (same prerequisite as A1/A2, so the guidance overlaps) and the
  default reset flow leaks account existence unless deliberately configured otherwise.
- **Case**: enabling self-service reset on a new realm.
- **Tooling**: mcp, rest · **Deps**: stock

**A16 — Remember-me and session persistence**
- **What**: realm `rememberMe`, the resulting persistent cookie, and its interaction with SSO
  session idle/max timeouts.
- **Use when**: "keep me logged in", "remember me checkbox", "users get logged out too often".
- **Problem**: "logged out too often" is almost always a *timeout* problem misdiagnosed as a
  remember-me problem; the skill's value is routing the diagnosis correctly (see F8).
- **Case**: a consumer app wants 30-day sessions.
- **Tooling**: mcp, rest · **Deps**: stock

**A17 — Identity-first / username-then-method login**
- **What**: split the identifier step from the credential step so the flow can branch on who the
  user is (which is the mechanism A6, B1 and C3 all build on).
- **Use when**: "ask for email first, then decide", "identity-first login", "different login for
  different users".
- **Problem**: the choice of identifier authenticator is load-bearing and already documented as a
  trap in A2's reference — stock `auth-username-form` leaks account existence before the next step
  runs. That finding deserves a first-class home rather than being buried in one intent.
- **Case**: routing users to SSO, passkey, or password based on their email address.
- **Tooling**: mcp, rest · **Deps**: p2 `keycloak-magic-link` (for `ext-auth-username-auth-note`)

**A18 — Authentication flow debugging**
- **What**: read a bound flow, resolve which flow is *effectively* in force (client override beats
  realm), enumerate executions with requirements and priorities, and correlate with login events.
- **Use when**: "my flow isn't triggering", "why is it still asking for a password", "which flow is
  actually being used".
- **Problem**: `skill-building-lessons.md` §2 records a verifier that failed a correct solution
  because it only checked realm-level binding while the answer was bound at client level. Agents
  make the same mistake. This is the diagnostic skill that prevents it.
- **Case**: an admin bound a custom flow and login behaviour didn't change.
- **Tooling**: mcp, rest · **Deps**: stock

---

### B. Identity brokering & user federation

`server_admin/topics/identity-broker/*` (26 files incl. 12 social providers),
`user-federation/*`. Four intents already exist here.

| # | Skill idea | Status |
|---|---|---|
| B1 | corporate SSO routed by email domain | ✅ done |
| B2 | consumer social login buttons | ✅ done |
| B3 | enterprise OIDC/SAML IdP federation (14 vendors) | ✅ done |
| B4 | org-restricted federated login (post-broker) | ✅ done |

**B5 — LDAP / Active Directory user federation**
- **What**: an LDAP user-storage provider — connection and bind, edit mode
  (`READ_ONLY`/`WRITABLE`/`UNSYNCED`), user/group DN and object classes, sync strategies,
  and attribute mappers.
- **Use when**: "connect Active Directory", "LDAP users", "sync users from our directory", "AD
  authentication".
- **Problem**: ~~the single most-requested capability the current router explicitly refuses~~ —
  **corrected: this is not a gap.** Five MCP tools already exist — `createLdapUserStorage`,
  `testLdapConnection`, `syncLdapUsers`, `listUserStorageProviders`, `deleteUserStorageProvider`.
  `SKILL.md`'s frontmatter and its `admin:idp-federation` Step 3 note both still say "no MCP tool
  exists for it," which is a **live mis-route** and should be fixed independently of this roadmap.

  This entry is also the worked example for §3's tool-absorbs-skill test. The two traps it cites
  are already dead: `editMode` **defaults to `READ_ONLY`**, so the irreversible-write-back failure
  cannot happen by omission, and `usernameLDAPAttribute` / `rdnLDAPAttribute` /
  `uuidLDAPAttribute` each document their own AD-vs-other default (`sAMAccountName` / `objectGUID`
  vs `uid` / `entryUUID`). The tool's response returns a `nextStep` pointing at
  `testLdapConnection` then `syncLdapUsers`, carrying the ordering too. A safe default beats a
  paragraph warning, because it applies when nobody read the paragraph.
- **Case**: an enterprise wants staff to log in with existing AD credentials, no user migration.
- **Outcome**: **tool exists** (§4.2) — close this idea. LDAP *mappers* beyond the defaults are a
  Wave 3 `createComponent` gap.
- **Tooling**: mcp, rest · **Deps**: stock

**B6 — IdP claim/attribute mappers**
- **What**: map incoming claims or SAML attributes onto Keycloak user attributes, roles, and
  groups — including hardcoded-role and advanced-claim-to-role mappers.
- **Use when**: "map groups from Okta to roles", "the user's department isn't coming through",
  "assign roles based on an IdP claim", "SAML attribute mapping".
- **Problem**: B3 creates the IdP but stops at the connection; every real federation project then
  fails on mapping. Also `syncMode` (`IMPORT` vs `FORCE` vs `LEGACY`) decides whether changes ever
  reach existing users, and the default surprises people.
- **Case**: a customer's Entra ID groups need to become Keycloak realm roles on every login.
- **Tooling**: mcp, rest · **Deps**: stock

**B7 — First-login flow and account linking**
- **What**: the first-broker-login flow — `review profile`, `create user if unique`, and the
  automatic vs. confirmed link-to-existing-account paths.
- **Use when**: "users get an 'account already exists' screen", "link the IdP to an existing
  account", "stop asking federated users to review their profile", "auto-link by email".
- **Problem**: the default flow's profile-review and duplicate-email confrontation are the two
  complaints that follow every B3 rollout, and auto-linking by unverified email is a real account-
  takeover vector — so the skill has to say when *not* to do the thing being asked for.
- **Case**: a user with a local password now signs in via corporate SSO and hits the link screen.
- **Tooling**: mcp, rest · **Deps**: stock

**B8 — Federated logout and session propagation**
- **What**: backchannel/frontchannel logout to the upstream IdP, SAML single logout, and the
  session-data linkage that makes it work.
- **Use when**: "logging out of my app doesn't log them out of Okta", "single logout", "SLO",
  "session stays alive after logout".
- **Problem**: logout is asymmetric with login — configuring the IdP for login says nothing about
  logout, and partial logout is a security finding, not a cosmetic bug.
- **Case**: a security review requires that app logout terminates the IdP session too.
- **Tooling**: mcp, rest · **Deps**: stock

**B9 — Retrieving and using the external IdP token**
- **What**: `storeToken` plus the broker retrieve-token role, and the endpoint that hands the
  upstream access token to the application.
- **Use when**: "call the Microsoft Graph API with the user's token", "get the Google access token
  after login", "use the IdP token downstream".
- **Problem**: it needs three things at once (a store flag, a role grant, a specific endpoint) and
  most attempts miss the role grant and get an opaque 403.
- **Case**: an app reads the signed-in user's Outlook calendar.
- **Tooling**: rest · **Deps**: stock

**B10 — Generic OIDC IdP for an unlisted vendor**
- **What**: brokering any OIDC or SAML 2.0 provider that isn't one of B3's 14 vendors, from a
  discovery URL or metadata document, including how to compute Keycloak's SP values up front.
- **Use when**: "connect \<vendor nobody has heard of\>", "our IdP just gives us a metadata URL",
  "generic SAML provider".
- **Problem**: the reference manifest already names this as an explicit gap ("any generic OIDC/SAML
  vendor outside the 14 above have no dedicated walkthrough yet"). The mechanics are vendor-
  independent; only the console click-path isn't, and for an unlisted vendor there is no click-path
  to write — so the skill's job is to teach the *pattern* and say what to ask the vendor for.
- **Case**: a customer's in-house IdP needs brokering with only a metadata endpoint to go on.
- **Tooling**: mcp, rest · **Deps**: stock

**B11 — Custom user storage provider (federate a non-LDAP source)**
- **What**: implement `UserStorageProvider` against a legacy database or REST API.
- **Use when**: "authenticate against our existing users table", "we have a legacy user API",
  "migrate users gradually".
- **Problem**: this is `code`-shaped, not API-shaped, and belongs in **L** — cross-listed here
  because developers arrive at it via "user federation" phrasing and need to be told which
  category they're actually in.
- **Case**: authenticating against a 15-year-old MySQL users table during a phased migration.
- **Tooling**: code · **Deps**: stock · **See**: L4

---

### C. Organizations & multi-tenancy

`server_admin/topics/organizations/*` (8 files) — plus p2-inc `keycloak-orgs`, which predates and
differs from Keycloak's own organizations feature.

| # | Skill idea | Status |
|---|---|---|
| C1 | restrict login to an organization's members (local) | ✅ done |

Two adjacent existing intents live in other categories: federated org-restriction is **B4**
(it binds to the IdP's post-broker flow, so it belongs with brokering), and cluster/deployment
provisioning is **N1**/**N2**.

**C4 — Choosing between Keycloak organizations and p2-inc `keycloak-orgs`**
- **What**: a decision guide — the two are different features with overlapping vocabulary; upstream
  organizations shipped in 26.x while `keycloak-orgs` has its own REST surface at
  `/realms/{realm}/orgs` and its own authenticators (`ext-select-org`).
- **Use when**: "should I use organizations or the Phase Two orgs extension", "which orgs API",
  "organizations vs orgs", or implicitly whenever a request mentions organizations at all.
- **Problem**: every existing org intent requires `keycloak-orgs`, so an agent on vanilla 26.x
  Keycloak will follow those references and find neither the endpoint nor the authenticator. This
  is a routing prerequisite for C1/C2 and B4, not an optional nicety.
- **Case**: a self-managed 26.6 user asks for org-restricted login and has no p2 extensions.
- **Tooling**: mcp, rest · **Deps**: both

**C5 — Create and manage organizations (upstream feature)**
- **What**: enable `organizationsEnabled`, create organizations, add verified domains, invite and
  manage members, organization attributes.
- **Use when**: "multi-tenant Keycloak", "one realm per customer vs one org per customer", "invite
  users to an organization", "B2B tenants".
- **Problem**: the realm-per-tenant vs organization-per-tenant decision is architectural and hard
  to reverse; and the *domain verification* step is what makes domain-based routing work at all.
- **Case**: a B2B SaaS onboarding its second enterprise customer into one realm.
- **Tooling**: mcp, rest · **Deps**: stock (26.x; `DEFAULT` from 26.6, preview earlier — see J7)

**C6 — Organization claims in tokens**
- **What**: the organization scope and mapper that puts organization membership into the access
  token or ID token.
- **Use when**: "my app needs to know which tenant the user belongs to", "org claim in the JWT",
  "tenant ID in the token".
- **Problem**: without this, an application has organizations in Keycloak and no way to act on
  them, and the mapper isn't on by default.
- **Case**: an API gateway routes requests by tenant using a token claim.
- **Tooling**: mcp, rest · **Deps**: stock (26.x)

**C7 — Per-organization identity providers**
- **What**: link an IdP to an organization so each tenant brings its own SSO, including the
  redirect/`kc_org` behaviour.
- **Use when**: "each customer has their own SSO", "per-tenant identity provider", "customer-managed
  SSO".
- **Problem**: B1 covers domain-routing generally; this is the organization-owned variant, and B4's
  reference already notes the org-owned IdP link is what makes the membership gate function.
- **Case**: 40 enterprise tenants, each with a different IdP, in one realm.
- **Tooling**: mcp, rest · **Deps**: stock (26.x) or p2 `keycloak-orgs`

**C8 — Organization roles and group mapping**
- **What**: organization-scoped roles and groups, and how they surface in tokens.
- **Use when**: "org admin vs org member", "let the customer manage their own users", "tenant
  admin role".
- **Problem**: delegated tenant administration is the reason customers ask for organizations, and
  it needs both org roles and **E4**'s admin delegation to actually work.
- **Case**: giving each tenant an "org admin" who can invite their own colleagues.
- **Tooling**: mcp, rest · **Deps**: stock (26.x) or p2 `keycloak-orgs`

---

### D. Users, profile & identity governance

`server_admin/topics/users/*` (21 files), `users/user-profile.adoc`, `workflows/*` (13 files).
No intents exist yet. **Workflows is the single largest untouched surface in the docs.**

**D1 — Declarative user profile (attributes, validation, UI annotations)**
- **What**: the user-profile JSON — attribute definitions, required/permission scoping per context,
  built-in validators, managed vs unmanaged attributes, attribute groups, annotations that drive
  form rendering.
- **Use when**: "add a custom field to registration", "make phone number required", "validate the
  employee ID format", "hide an attribute from users", "unmanaged attributes".
- **Problem**: this replaced ad-hoc attribute handling and is now the *only* correct way to add user
  fields, but a model trained on older Keycloak will reach for realm attribute mappers or theme
  edits instead. The managed/unmanaged distinction also silently drops attributes that aren't
  declared.
- **Case**: a signup form needs a required company field with regex validation, editable by admins
  but read-only to users.
- **Tooling**: mcp, rest · **Deps**: stock

**D2 — Self-registration**
- **What**: enable registration, the registration flow, email verification, terms and conditions,
  and reCAPTCHA.
- **Use when**: "let users sign themselves up", "public signup", "email verification", "stop bot
  signups", "require terms acceptance".
- **Problem**: four separate settings across three surfaces (realm flags, flow executions, required
  actions, user profile) have to line up; and enabling registration without reCAPTCHA or email
  verification is an abuse vector that gets discovered in production.
- **Case**: a consumer product opening public signup.
- **Tooling**: mcp, rest · **Deps**: stock

**D3 — Required actions and application-initiated actions**
- **What**: the required-action catalogue, defaults for new users, setting them per user, and AIA
  (`kc_action`) so an app can trigger e.g. password update or passkey enrolment on demand.
- **Use when**: "force a password change at next login", "make users set up 2FA", "let users add a
  passkey from my app's settings page", "update profile prompt".
- **Problem**: AIA is the correct answer to "how does my app let a user enrol a credential" and is
  almost never the first thing tried; A4's reference already needs it for credential bootstrap.
- **Case**: an app's security settings page offers "Add a passkey".
- **Tooling**: mcp, rest · **Deps**: stock

**D4 — User CRUD and bulk operations**
- **What**: create/search/update/delete users, set credentials, attribute search, pagination, and
  the count/search semantics that differ from what people expect.
- **Use when**: "create 500 users", "find users by attribute", "bulk import", "delete a user and
  all their sessions".
- **Problem**: the baseline capability everything else assumes; the search API's exact-vs-infix
  behaviour and pagination limits cause silent partial results in scripts.
- **Case**: onboarding a customer's staff list from a CSV.
- **Tooling**: mcp, rest · **Deps**: stock

**D5 — User impersonation**
- **What**: the impersonation endpoint and permission, and its audit trail.
- **Use when**: "log in as a customer to debug", "support impersonation", "view the app as this
  user".
- **Problem**: hugely useful for support and a serious privilege-escalation risk; the skill's job
  is as much about scoping the permission and auditing it as about turning it on.
- **Case**: a support engineer reproduces a customer's reported bug.
- **Tooling**: rest · **Deps**: stock

**D6 — Workflows: automated joiner-mover-leaver (JML)**
- **What**: define a workflow with conditions, steps, scheduling, and failure handling to provision
  and de-provision users automatically on events or time.
- **Use when**: "automate onboarding", "disable accounts when someone leaves", "JML", "identity
  lifecycle", "provisioning automation".
- **Problem**: brand-new 26.6 engine (13 doc files) that no model has reliable knowledge of, with
  its own expression language. An agent asked for this today will hand-roll a cron job against the
  Admin API instead of using the built-in engine.
- **Case**: HR marks an employee as terminated; their account and sessions are revoked within an
  hour.
- **Tooling**: rest · **Deps**: stock (26.6+)

**D7 — Workflows: inactive-account cleanup and access reviews**
- **What**: scheduled workflows that find dormant users, notify, then disable or delete; and
  periodic access-review/certification workflows.
- **Use when**: "delete users who haven't logged in for a year", "dormant account policy", "access
  certification", "SOC 2 access review", "GDPR retention".
- **Problem**: compliance-driven and previously required custom code; also genuinely destructive, so
  the skill must lead with the dry-run/notify-first pattern rather than the delete step.
- **Case**: an auditor requires evidence that inactive accounts are removed within 90 days.
- **Tooling**: rest · **Deps**: stock (26.6+)

**D8 — Workflow expressions and troubleshooting**
- **What**: the workflow definition schema, expression syntax, event listening, and the
  troubleshooting surface.
- **Use when**: "my workflow didn't run", "workflow expression syntax", "debug a workflow".
- **Problem**: a new DSL with its own failure modes; D6/D7 are useless without a way to see why a
  workflow silently did nothing.
- **Case**: a JML workflow fires for some users and not others.
- **Tooling**: rest · **Deps**: stock (26.6+)

**D9 — Account console and self-service**
- **What**: what users can do for themselves — profile, credentials, device/session management,
  linked accounts, application consent, self-deletion.
- **Use when**: "let users manage their own profile", "self-service password change", "let users see
  their active sessions", "account deletion", "GDPR self-service".
- **Problem**: reduces support load and is often assumed absent; self-deletion in particular is a
  separately-enabled capability that GDPR requests need.
- **Case**: a product needs a "manage your account" link that isn't custom-built.
- **Tooling**: mcp, rest · **Deps**: stock

**D10 — Personal data and GDPR posture**
- **What**: what Keycloak stores about a user (`ref-personal-data-collected.adoc`), where, for how
  long, and how to export or erase it.
- **Use when**: "GDPR data subject request", "what PII does Keycloak hold", "right to erasure",
  "data retention".
- **Problem**: answering a DSAR requires knowing about user attributes, sessions, events, and
  federated links — four stores, not one. Upstream documents this explicitly and almost nobody
  reads it.
- **Case**: a DSAR arrives and someone has to produce everything held about one person.
- **Tooling**: rest · **Deps**: stock

---

### E. Roles, groups & admin delegation

`server_admin/topics/roles-groups/*` (10 files), `admin-console-permissions/*` (5 files).
No intents yet.

**E1 — Realm and client roles, and composite roles**
- **What**: create realm vs client roles, composite roles, default roles, and role scope mappings.
- **Use when**: "add an admin role", "role hierarchy", "nested roles", "give every new user this
  role", "roles aren't in my token".
- **Problem**: "roles aren't in my token" is a *scope mapping* problem (see F4), not a role
  problem, and the two get conflated constantly. Composite roles also expand at token time in ways
  that surprise people auditing a token.
- **Case**: modelling `admin`/`editor`/`viewer` across two applications.
- **Tooling**: mcp, rest · **Deps**: stock

**E2 — Groups, subgroups and default groups**
- **What**: group hierarchies, role inheritance down the tree, group attributes, default groups for
  new users, and the group-membership token mapper.
- **Use when**: "organise users into teams", "nested groups", "inherit permissions from a parent
  group", "put new users in a default group".
- **Problem**: upstream has a whole doc on groups-vs-roles because people pick wrong and then can't
  migrate; and group *membership* is not in tokens unless a mapper is added.
- **Case**: departments as groups, with departmental roles inherited by members.
- **Tooling**: mcp, rest · **Deps**: stock

**E3 — Groups vs roles: choosing a model**
- **What**: the decision guide — roles as permissions, groups as collections, and when to use
  attributes instead of either.
- **Use when**: "should this be a role or a group", "how do I model permissions", "access control
  design".
- **Problem**: an architectural decision that's expensive to reverse, and upstream ships a dedicated
  comparison page (`con-comparing-groups-roles.adoc`) precisely because it's the most common
  early mistake.
- **Case**: greenfield realm design for a product with 3 tiers and 6 permissions.
- **Tooling**: mcp, rest · **Deps**: stock

**E4 — Fine-grained admin permissions (v2)**
- **What**: policy-based delegation of realm administration — scoped permissions on users, groups,
  and clients, and the three admin types (server, realm, delegated).
- **Use when**: "let this team manage only their own users", "delegated administration", "scoped
  admin", "help-desk role that can reset passwords but nothing else", "tenant admin".
- **Problem**: substantially reworked — verified in `Profile.java` that v1
  (`admin-fine-grained-authz`) is now `Type.DEPRECATED` while v2 is `Type.DEFAULT`, yet **both**
  docs are still in the tree, so an agent has a 50% chance of following the deprecated one. It also
  *interacts* with RBAC in a non-obvious way: per `fine-grain-v2.adoc`, granting a role like
  `view-users` "will skip the mechanisms provided by this feature", and server/realm admins are
  exempt entirely. Getting that wrong produces delegation that silently grants everything.
- **Case**: a help desk that can reset passwords for one group and nothing else.
- **Tooling**: rest · **Deps**: stock

**E5 — Master realm vs per-realm admin access**
- **What**: the master-realm admin model, per-realm admin roles, and when to use which.
- **Use when**: "who should have admin", "separate admins per realm", "master realm access",
  "cross-realm administration".
- **Problem**: prerequisite context for E4, and the master realm's cross-realm power is routinely
  handed out too broadly because it's the path of least resistance.
- **Case**: a hosting provider giving each customer admin over their own realm only.
- **Tooling**: rest · **Deps**: stock

---

### F. Clients, protocols & sessions

`server_admin/topics/clients/*` (20 files), `sso-protocols/*` (7 files), `sessions/*` (6 files).
No intents yet — and this is the category most requests actually start from.

**F1 — Create and configure an OIDC client**
- **What**: public vs confidential vs bearer-only, redirect URI and web-origin rules, the enabled
  grant types, and the advanced settings that matter.
- **Use when**: "create a client for my app", "invalid redirect_uri", "set up OIDC for my SPA",
  "which client type do I need".
- **Problem**: the most common first task and the most common source of "it doesn't work": wildcard
  redirect URIs are both the usual fix and an open-redirect vulnerability, and public-vs-confidential
  is chosen wrongly for SPAs and native apps roughly always.
- **Case**: registering a new React front end and its backend API.
- **Tooling**: mcp, rest · **Deps**: stock

**F2 — Create and configure a SAML client**
- **What**: SAML SP registration, entity descriptors, name-ID format, signing and encryption keys,
  binding choices, and IdP-initiated login.
- **Use when**: "SAML app", "our vendor sent us a metadata file", "SP-initiated vs IdP-initiated",
  "SAML signature error".
- **Problem**: an entirely different config surface from OIDC with its own failure vocabulary; most
  errors reduce to a signing/canonicalisation mismatch that the error message doesn't name.
- **Case**: integrating a legacy HR system that only speaks SAML 2.0.
- **Tooling**: mcp, rest · **Deps**: stock

**F3 — Service accounts and the client-credentials grant**
- **What**: enable a service account, grant it roles, and obtain machine-to-machine tokens.
- **Use when**: "machine to machine", "API key equivalent", "backend service needs a token", "cron
  job authentication", "client credentials".
- **Problem**: the standard answer to "how does my service authenticate", and the role grant goes
  on the *service account user*, not the client — a distinction that costs people an afternoon.
- **Case**: a nightly batch job calling an internal API.
- **Tooling**: mcp, rest · **Deps**: stock

**F4 — Client scopes and protocol mappers**
- **What**: default vs optional client scopes, the built-in mappers, custom claim mappers, audience
  mappers, and the scope-evaluation tool.
- **Use when**: "add a claim to the token", "roles/groups missing from my JWT", "shrink my token",
  "audience validation fails", "what will be in the token".
- **Problem**: the highest-traffic troubleshooting topic in the whole product, and Keycloak ships a
  scope-evaluation tool that answers it definitively — which nobody uses because they don't know it
  exists. Lead the skill with that tool.
- **Case**: an API rejects tokens because `aud` doesn't match.
- **Tooling**: mcp, rest · **Deps**: stock

**F5 — Token lifespans and refresh behaviour**
- **What**: access/refresh/ID token lifespans, refresh-token rotation and reuse limits, offline
  tokens, and how these interact with SSO session limits.
- **Use when**: "tokens expire too fast", "refresh token stopped working", "long-lived token",
  "offline access", "how long should tokens live".
- **Problem**: the settings live at both realm and client level with client winning, and a refresh
  token can't outlive the SSO session no matter what the token setting says — the usual cause of
  "my refresh token expired early".
- **Case**: a mobile app that must stay signed in for weeks.
- **Tooling**: mcp, rest · **Deps**: stock

**F6 — Standard token exchange**
- **What**: RFC 8693 token exchange as implemented by the *standard* (not legacy) mechanism —
  enabling it, request/response parameters, scope and audience handling.
- **Use when**: "exchange a token for a downstream service", "on-behalf-of", "token exchange",
  "service-to-service with the user's identity", "delegation".
- **Problem**: upstream ships an explicit comparison section because standard and legacy exchange
  coexist with different enablement, semantics and security properties. Verified in
  `Profile.java`: `token-exchange-standard-v2` is `Type.DEFAULT` while the legacy
  `token-exchange` is `Type.PREVIEW` — so the modern one is on and the old one needs a flag, the
  reverse of what older tutorials imply. A model will very likely produce the legacy form, and the
  legacy doc's own "Exchange vulnerabilities" and "Direct Naked Impersonation" sections explain why
  that matters.
- **Case**: an API gateway exchanges the caller's token for one scoped to a backend.
- **Tooling**: rest · **Deps**: stock

**F7 — Client secret rotation**
- **What**: rotation policy via client policies, the rotated-secret grace period, and doing it
  without an outage.
- **Use when**: "rotate client secrets", "secret compromised", "credential rotation policy",
  "rotate without downtime".
- **Problem**: naive rotation is an instant outage; the grace-period mechanism exists precisely to
  avoid that and is not discoverable.
- **Case**: quarterly secret rotation mandated by policy, across 20 clients.
- **Tooling**: rest · **Deps**: stock

**F8 — Session management and timeouts**
- **What**: SSO session idle and max, client session limits, remember-me overrides, and the
  admin-side view of who is logged in.
- **Use when**: "users get logged out too soon", "how long do sessions last", "force logout",
  "session limits per user", "see active sessions".
- **Problem**: five interacting timeout values where the shortest wins; diagnosing "logged out too
  soon" without a map of them is guesswork (and A16 is where people wrongly look first).
- **Case**: a bank wants a 15-minute idle timeout and an 8-hour hard cap.
- **Tooling**: mcp, rest · **Deps**: stock

**F9 — Logout and token revocation**
- **What**: OIDC RP-initiated logout, backchannel logout to clients, `not-before` pushes, and
  revoking specific sessions or offline tokens.
- **Use when**: "log the user out of everything", "revoke a token", "backchannel logout", "kill a
  compromised session", "single logout".
- **Problem**: access tokens are self-contained and cannot be un-issued — revocation is about
  sessions and refresh tokens plus short lifespans, and the skill has to say that plainly rather
  than promising instant revocation.
- **Case**: an incident response requires terminating one user's access immediately.
- **Tooling**: rest · **Deps**: stock

**F10 — Offline tokens, and transient sessions for service accounts**
- **What**: offline tokens for long-lived background access; and transient sessions — which are
  **not** a setting you enable but an automatic optimization Keycloak applies during service-account
  authentication when token refresh is disabled.
- **Use when**: "offline access", "background sync without the user present", "service account
  sessions are filling the database", "why is `sid` empty in my client-credentials token".
- **Problem**: the transient-session half is widely mis-stated as a configurable mode. Per
  `sessions/transient.adoc` the only lever is the client switch **Use refresh tokens for client
  credentials grant** — turning it *on* silently disables the optimization and starts persisting a
  session per machine token, which is exactly how a high-volume service account floods the session
  store. Offline tokens are the standard answer for background jobs but have distinct revocation
  behaviour.
- **Case**: a service account issuing thousands of tokens an hour with no need to refresh any of
  them.
- **Tooling**: rest · **Deps**: stock

**F11 — Dynamic client registration**
- **What**: the client-registration endpoint, initial access tokens, registration access tokens,
  policies, and the registration CLI.
- **Use when**: "clients register themselves", "programmatic client creation", "multi-tenant client
  onboarding", "OIDC dynamic registration".
- **Problem**: the correct answer for platforms that onboard clients at scale, gated by registration
  *policies* that must be configured or the endpoint is either closed or dangerously open.
- **Case**: a developer portal where third parties self-register OAuth apps.
- **Tooling**: rest, cli · **Deps**: stock

**F12 — Client policies and profiles**
- **What**: conditions and executors that enforce configuration standards across clients, rather
  than per-client settings.
- **Use when**: "enforce PKCE on every client", "no wildcard redirect URIs anywhere", "org-wide
  client standards", "FAPI compliance".
- **Problem**: the only scalable way to enforce security posture across many clients, and the
  mechanism behind both F7 and the FAPI/OAuth 2.1 profiles in **O**.
- **Case**: a platform team mandates PKCE and exact redirect URIs for all new clients.
- **Tooling**: rest · **Deps**: stock

**F13 — Client authentication methods beyond secrets**
- **What**: `private_key_jwt`, mTLS client authentication, and the JWT bearer authorization grant.
- **Use when**: "certificate-based client auth", "no shared secrets", "private_key_jwt", "mTLS
  client authentication", "FAPI requires asymmetric client auth".
- **Problem**: required by FAPI and by many enterprises' no-shared-secret policies; the key/JWKS
  registration half is where it fails.
- **Case**: a financial-services client must authenticate with a signed JWT, not a secret.
- **Tooling**: rest · **Deps**: stock

---

### G. Authorization services (fine-grained resource authorization)

`authorization_services/*` (52 files). An entire guide with zero coverage. Distinct from **E** —
that's *who can administer Keycloak*, this is *what your application's users may do to your
application's resources*.

**G1 — Turn a client into a resource server**
- **What**: enable authorization on a confidential client, and the resource/scope/policy/permission
  model with its terminology.
- **Use when**: "fine-grained authorization", "ABAC", "policy-based access control", "permissions
  beyond roles", "Keycloak as a PDP".
- **Problem**: a four-concept model (resource, scope, policy, permission) where every term collides
  with something else in Keycloak; without the vocabulary straight, nothing else in this category
  can be followed.
- **Case**: a document management app needs per-document permissions.
- **Tooling**: rest · **Deps**: stock

**G2 — Resources and scopes**
- **What**: define resource types, URIs, owners, and authorization scopes; typed resources for
  instance-level permissions.
- **Use when**: "per-object permissions", "resource-level access", "each user owns their own
  records".
- **Problem**: the typed-resource pattern is what makes this scale to many instances instead of
  requiring one resource per row — non-obvious and the difference between workable and not.
- **Case**: every uploaded file is a resource owned by its uploader.
- **Tooling**: rest · **Deps**: stock

**G3 — Policies (role, group, user, time, regex, client-scope, aggregate)**
- **What**: the built-in policy types, decision strategies (`AFFIRMATIVE`/`UNANIMOUS`/`CONSENSUS`),
  and combining them.
- **Use when**: "only during business hours", "managers and only in this group", "combine
  conditions", "complex authorization rules".
- **Problem**: decision strategy is set in two places (policy and permission) and the interaction
  is the usual source of "why was this allowed".
- **Case**: approvals permitted only to managers, only on weekdays, only for their own department.
- **Tooling**: rest · **Deps**: stock

**G4 — JavaScript policies**
- **What**: script-based policies — deploying them as a provider JAR (they can't be uploaded at
  runtime any more) and the evaluation context API.
- **Use when**: "custom authorization logic", "policy in code", "attribute-based rules the built-in
  types can't express".
- **Problem**: the deployment model changed — uploading scripts through the console was removed for
  security reasons, so every pre-26 tutorial is wrong. Also `code`-shaped, so it needs **L**.
- **Case**: a rule comparing a token claim against a resource attribute.
- **Tooling**: code · **Deps**: stock

**G5 — Enforcing permissions in an application**
- **What**: obtaining an RPT, the policy-enforcer configuration, token introspection of permissions,
  and pushing claims.
- **Use when**: "how does my app check permissions", "policy enforcement point", "RPT", "call
  Keycloak to authorize a request".
- **Problem**: without this the whole category is theoretical — this is the half that runs in the
  application, and the latency/caching trade-offs decide whether it's usable in production.
- **Case**: a Node API asks Keycloak whether the caller may delete a given record.
- **Tooling**: framework · **Deps**: stock

**G6 — Policy evaluation and debugging**
- **What**: the built-in evaluation tool and the evaluation API — simulate a decision for a given
  user, resource and scope before shipping.
- **Use when**: "why was access denied", "test my policy", "debug authorization", "simulate a
  permission check".
- **Problem**: the only practical way to develop non-trivial policies, and per the same lesson as
  F4, agents don't reach for built-in evaluation tools unless told to.
- **Case**: a policy denies a user who should be allowed and nobody can see why.
- **Tooling**: rest · **Deps**: stock

**G7 — UMA and user-managed sharing**
- **What**: the UMA 2.0 flow — permission tickets, the protection API, and letting end users share
  their own resources.
- **Use when**: "let users share their documents", "user-managed access", "share with a colleague",
  "resource sharing like Google Docs".
- **Problem**: a genuinely differentiating capability that's almost unknown, and the ticket flow is
  hard to get right from first principles.
- **Case**: users grant colleagues read access to their own files.
- **Tooling**: rest · **Deps**: stock

**G8 — Import/export an authorization configuration**
- **What**: the resource-server JSON config — moving an authorization model between environments.
- **Use when**: "promote authz config to production", "version-control my policies", "GitOps for
  authorization".
- **Problem**: building an authorization model by hand twice is untenable; the JSON round-trip is
  the only reasonable path and has export/import asymmetries worth documenting.
- **Case**: promoting a 40-permission model from staging to production.
- **Tooling**: rest · **Deps**: stock

---

### H. Securing applications (per framework)

`docs/guides/securing-apps/*` (50 files). The repo README already promises this: *"skills for
coding agents to configure Keycloak instances **and protect their applications using many
frameworks**."* Nothing exists yet. The tooling axis here is the **framework**, not mcp-vs-rest.

**H1 — Integration decision guide**
- **What**: pick the right pattern first — BFF vs public SPA client, which grant, where tokens
  live, whether a library or a proxy is appropriate.
- **Use when**: "how do I add Keycloak to my app", "which OIDC library", "should I store tokens in
  localStorage", "auth code + PKCE or implicit".
- **Problem**: routing prerequisite for everything else in this category, and the place the biggest
  security mistakes are made (implicit flow, tokens in local storage, secrets in a browser bundle).
- **Case**: a team starting integration with no idea which of six patterns applies.
- **Tooling**: framework · **Deps**: stock

**H2–H11 — Per-framework integration**
Same shape for each, differing only in the library, config file, and callback wiring:

| # | Framework | Notes on what makes it distinct |
|---|---|---|
| H2 | React / Vue SPA | `keycloak-js` or `oidc-client-ts`; PKCE mandatory, silent renew, no secret |
| H3 | Next.js / Nuxt (SSR) | route handlers, cookie-based sessions, the server/client token split |
| H4 | Node / Express | session middleware, backchannel logout endpoint, token verification |
| H5 | Spring Boot | `spring-boot-starter-oauth2-*`, resource server vs client, role converter for Keycloak's claim shape |
| H6 | Quarkus | `quarkus-oidc` — directly relevant to `phasetwo-mcp` itself; discovery, `jwks-path`, issuer pinning |
| H7 | Python (FastAPI / Flask / Django) | token validation, no first-party library, JWKS caching |
| H8 | Go | `coreos/go-oidc`, manual verification |
| H9 | .NET | `AddOpenIdConnect`, claim mapping quirks |
| H10 | Mobile / native (iOS, Android, React Native) | AppAuth, PKCE, system browser vs webview, custom URI schemes |
| H11 | Reverse-proxy / gateway (oauth2-proxy, `mod_auth_openidc`, Envoy, NGINX) | protecting apps with no auth code at all; upstream documents `mod_auth_openidc` and `mod_auth_mellon` specifically |

- **Use when** (all): "add login to my \<framework\> app", "\<framework\> Keycloak example", "verify
  a JWT in \<language\>".
- **Problem** (all): every framework has a different idiomatic integration and a different set of
  Keycloak-specific gotchas (claim shapes, role locations, issuer/hostname mismatches behind a
  proxy). Generic OIDC advice produces code that authenticates but gets roles wrong.
- **Tooling**: framework · **Deps**: stock

**H12 — Keycloak as the authorization server for an MCP server**
- **What**: the RFC 9728 protected-resource metadata, resource indicators (RFC 8707), dynamic client
  registration, and which MCP spec versions Keycloak satisfies.
- **Use when**: "secure my MCP server", "OAuth for MCP", "MCP authorization", "claude.ai custom
  connector authentication", "WWW-Authenticate resource metadata".
- **Problem**: an upstream guide that exists only in recent versions, spanning four MCP spec
  revisions with different mandatory standards. Also the most directly self-relevant skill in the
  catalogue — it's what `phasetwo-mcp` implements. Strong candidate for early build because we can
  verify it against our own deployment.
- **Case**: someone wants their MCP server to accept Keycloak-issued tokens from an MCP client.
- **Tooling**: rest, framework · **Deps**: stock (26.x)

**H13 — Token verification and validation done right**
- **What**: JWKS retrieval and caching, issuer and audience validation, `azp`, clock skew,
  algorithm pinning, and when to introspect instead of verify locally.
- **Use when**: "validate a JWT", "verify the token in my API", "should I call introspection",
  "invalid issuer".
- **Problem**: the most security-critical code any integrator writes, and the most commonly wrong —
  skipping audience checks, accepting `none`, trusting an issuer from the token itself. The
  hostname/issuer mismatch behind a proxy (see J4) is the top real-world failure.
- **Case**: a Python API validating tokens with no framework support.
- **Tooling**: framework · **Deps**: stock

**H14 — Multi-tenant applications**
- **What**: one app serving several realms or organizations — resolving tenant from host, path, or
  claim, and per-tenant issuer configuration.
- **Use when**: "one app many realms", "multi-tenant SaaS", "per-customer realm", "tenant
  resolution".
- **Problem**: cross-cuts C5's realm-vs-organization decision and forces application-side design;
  upstream documents SAML multi-tenancy but the OIDC side is left to the reader.
- **Case**: a SaaS with a realm per enterprise customer and one shared front end.
- **Tooling**: framework · **Deps**: stock

---

### I. Realm operations & lifecycle

`server_admin/topics/realms/*` (8 files), `events/*`, `vault.adoc`, `guides/server/importExport.adoc`.

**I1 — Create and configure a realm**
- **What**: realm creation and the settings that matter early — display name, frontend URL,
  required SSL, default locale, and which ones are painful to change later.
- **Use when**: "new realm", "realm settings", "set up a realm for staging", "realm vs
  organization".
- **Problem**: the base task for everything else, and several settings (frontend URL, SSL
  requirement) cause confusing downstream failures if set wrong.
- **Case**: standing up a staging realm alongside production.
- **Tooling**: mcp, rest · **Deps**: stock

**I2 — SMTP / email configuration**
- **What**: realm SMTP settings, from-address and display name, TLS/auth options, and verifying
  delivery.
- **Use when**: "emails aren't sending", "configure SMTP", "verification email never arrives",
  "SES/SendGrid with Keycloak".
- **Problem**: a hard prerequisite for A1, A2, A15, D2 and D6 — the most-shared dependency in the
  catalogue and the most common silent failure, since a bad SMTP config surfaces as "the feature
  doesn't work" rather than as a mail error.
- **Case**: enabling magic-link login and nothing arrives.
- **Tooling**: mcp, rest · **Deps**: stock

**I3 — Realm keys and key rotation**
- **What**: realm keystores and providers, active vs passive keys, algorithm choice, and rotating
  signing keys without invalidating live tokens.
- **Use when**: "rotate signing keys", "key compromised", "which algorithm should I sign with",
  "add an RSA key", "JWKS has two keys".
- **Problem**: rotation done wrong invalidates every token and session at once; the passive-key
  mechanism exists to prevent that and isn't obvious.
- **Case**: annual key rotation without downtime.
- **Tooling**: rest · **Deps**: stock

**I4 — Login and admin event logging**
- **What**: enable event storage, choose which event types to keep, set expiration, and enable the
  admin event log with representations.
- **Use when**: "audit log", "who changed this", "track failed logins", "SIEM integration", "event
  retention".
- **Problem**: **off by default**, so the audit trail people assume exists usually doesn't — and it
  can only be turned on prospectively. Storing representations also grows the database fast.
- **Case**: an audit asks who granted a role three weeks ago.
- **Tooling**: mcp, rest · **Deps**: stock

**I5 — Event listeners and external forwarding**
- **What**: configure event listener providers, and forward events to an external system (webhook,
  Kafka, SIEM) — including where the p2-inc webhook/event extensions fit.
- **Use when**: "send login events to our SIEM", "webhook on user creation", "stream Keycloak
  events", "react to a registration".
- **Problem**: the standard integration point for provisioning and analytics; the built-in surface
  is a provider interface, so this straddles config (**I**) and code (**L**).
- **Case**: pushing new-user events into a CRM.
- **Tooling**: rest, code · **Deps**: stock or p2 extensions

**I6 — Realm import and export**
- **What**: full and partial import/export, the file vs directory strategies, what does and doesn't
  round-trip, and the `--optimized`/bootstrap-time import path.
- **Use when**: "copy a realm to another environment", "back up my realm config", "realm as code",
  "promote config to production", "partial import".
- **Problem**: the manifest already documents a hard trap: `partialImport` **has no handler for
  authentication flows** and silently returns 200 while creating nothing. Secrets and users also
  don't round-trip the way people assume. This skill is where that knowledge belongs.
- **Case**: promoting a realm configuration from dev to production in CI.
- **Tooling**: rest, cli · **Deps**: stock

**I7 — Config as code / GitOps for realms**
- **What**: patterns for keeping realm configuration in version control — export shape, operator
  realm import, or declarative tooling — plus what must be applied out of band.
- **Use when**: "terraform for Keycloak", "realm config in git", "reproducible realms",
  "environment parity".
- **Problem**: everybody wants it, nothing does it completely; the honest answer includes what
  *cannot* be declared, which is exactly what an agent will otherwise invent.
- **Case**: three environments that must stay in sync.
- **Tooling**: rest, k8s, cli · **Deps**: stock

**I8 — Vault and secret management**
- **What**: the vault SPI, file-based and Kubernetes-secret vault providers, and `${vault.x}`
  references in realm config.
- **Use when**: "don't put the SMTP password in the realm export", "secrets in Kubernetes",
  "external secret store", "avoid plaintext credentials in config".
- **Problem**: the prerequisite that makes I6/I7 safe — without it, exported realm config contains
  live secrets, which is how they end up in git.
- **Case**: an LDAP bind password that must not appear in a realm JSON.
- **Tooling**: cli, k8s · **Deps**: stock

**I9 — Internationalization and locale selection**
- **What**: enable i18n, supported and default locales, locale resolution order, and overriding
  message bundles.
- **Use when**: "translate the login page", "multi-language", "i18n", "custom error message
  wording".
- **Problem**: overlaps theming (**M**) — message overrides are theme resources, so the two have to
  be routed together or the answer is half-complete.
- **Case**: a product launching in French and German.
- **Tooling**: rest, code · **Deps**: stock

---

### J. Server installation & configuration

`docs/guides/server/*` (30 files). Entirely uncovered, and a different work shape from everything
above: no Admin REST at all. Tooling axis is `{cli|conf-file|env|container|operator}`.

**J1 — First production configuration**
- **What**: the `configuration-production.adoc` checklist — TLS, hostname, database, proxy,
  health/metrics, and `kc.sh build` vs runtime options.
- **Use when**: "production Keycloak", "is my Keycloak production ready", "dev mode vs production
  mode", "start-dev in production".
- **Problem**: `start-dev` in production is the single most common serious misconfiguration, and
  the build-vs-runtime option split (recorded in `skill-building-lessons.md` §4 as a trap that cost
  a benchmark run) is genuinely confusing.
- **Case**: moving from a docker-compose demo to a real deployment.
- **Tooling**: cli, conf-file, container · **Deps**: stock

**J2 — Database configuration**
- **What**: supported databases, JDBC URL and pool settings, schema initialisation, and
  connection-pool sizing.
- **Use when**: "connect to PostgreSQL", "connection pool exhausted", "which database", "database
  timeouts under load".
- **Problem**: pool sizing interacts with thread configuration in a way documented only in the HA
  guide; the default is wrong for anything non-trivial.
- **Case**: production Postgres with 200 connections available.
- **Tooling**: cli, conf-file · **Deps**: stock

**J3 — TLS, truststores and outgoing HTTP**
- **What**: `enabletls`, the Keycloak truststore, mutual TLS, and outgoing HTTP client settings for
  IdP and webhook calls.
- **Use when**: "HTTPS for Keycloak", "PKIX path building failed", "self-signed certificate",
  "trust our internal CA".
- **Problem**: `PKIX path building failed` on an outbound IdP call is a top-five support issue and
  the fix (the truststore, not the JVM's) is not where people look.
- **Case**: brokering an internal IdP with a private CA certificate.
- **Tooling**: cli, conf-file · **Deps**: stock

**J4 — Hostname and reverse proxy**
- **What**: `hostname`, `hostname-admin`, `hostname-backchannel-dynamic`, proxy headers, and the
  split between frontend and backchannel URLs.
- **Use when**: "wrong redirect URL", "issuer mismatch", "behind ALB/NGINX/Ingress", "admin console
  loads without CSS", "invalid token issuer".
- **Problem**: the highest-frequency real-world failure in Keycloak operations, and it manifests as
  a *token validation* error (see H13), so people debug the wrong layer entirely. The hostname
  options were also reworked in v26, making pre-26 advice actively wrong.
- **Case**: Keycloak behind an ALB issuing tokens with an internal issuer URL.
- **Tooling**: cli, conf-file, k8s · **Deps**: stock

**J5 — Caching and clustering configuration**
- **What**: embedded Infinispan cache config, cache stack selection, `cache-config-file`, and
  remote-cache/external Infinispan setup.
- **Use when**: "cluster two Keycloak nodes", "sessions lost after restart", "nodes don't see each
  other", "cache configuration".
- **Problem**: "sessions lost on restart" and "logged out randomly behind a load balancer" are both
  clustering symptoms; the discovery stack choice is environment-specific and undiscoverable from
  the error.
- **Case**: three Keycloak pods that must share sessions.
- **Tooling**: cli, conf-file, k8s · **Deps**: stock

**J6 — Logging configuration**
- **What**: console/file/syslog handlers, per-category levels, JSON structured output, and MDC.
- **Use when**: "JSON logs", "log to syslog", "turn on debug for authentication", "reduce log
  noise", "ship logs to CloudWatch/Loki".
- **Problem**: per-category debug (`--log-level=org.keycloak.authentication:debug`) is the single
  most useful diagnostic in the product and is not widely known — it's a dependency of A18, F4 and
  J4 troubleshooting.
- **Case**: debugging a flow in production without turning on debug globally.
- **Tooling**: cli, conf-file · **Deps**: stock

**J7 — Feature flags**
- **What**: `--features` / `--features-disabled`, preview vs supported vs experimental tiers, and
  which features need a rebuild.
- **Use when**: "enable organizations", "preview feature", "experimental feature", "this option
  isn't in my console", "how do I turn on X", "is X supported".
- **Problem**: "the feature isn't in my console" is usually a disabled flag — but **which** flags
  are disabled moved between versions, which is the part that makes this hard. Checked against
  26.6's `Profile.java`: `organizations`, `workflows`, `admin-fine-grained-authz-v2`, `passkeys`,
  `dpop` and `token-exchange-standard-v2` are all `DEFAULT` now, while they were preview (or absent)
  in earlier 26.x releases; `transient-users`, `oid4vci` and external-to-internal token exchange are
  still `EXPERIMENTAL`. So version-specific advice is mandatory here, and enabling a preview feature
  has real upgrade implications (see K3).
- **Case**: following a 26.0-era tutorial that says to build with `--features=organizations`, on a
  26.6 server where it is already on by default.
- **Tooling**: cli, conf-file · **Deps**: stock

**J8 — Management interface (health, metrics, port 9000)**
- **What**: the separate management listener, `/health`, `/health/ready`, `/health/live`, `/metrics`,
  and why it's on a different port.
- **Use when**: "health check endpoint", "readiness probe", "Prometheus scrape", "load balancer
  health check fails", "which port is /health on".
- **Problem**: the port split trips up every load-balancer and Kubernetes configuration on first
  contact — the same issue solved in `phasetwo-mcp`'s own target group (health checks on 9000,
  traffic on 8080). `skill-building-lessons.md` §4 also records that
  `quarkus.management.enabled` is build-time only.
- **Case**: an ALB target group failing health checks against port 8080.
- **Tooling**: cli, k8s · **Deps**: stock

**J9 — Provider configuration and custom provider deployment**
- **What**: `providers/` JAR deployment, `--spi-*` configuration options, `configuration-provider`,
  and which changes require `kc.sh build`.
- **Use when**: "install this Keycloak extension", "deploy a provider jar", "configure an SPI",
  "my extension isn't loading".
- **Problem**: the mechanism by which every p2-inc extension the existing skills depend on gets
  installed — `keycloak-magic-link`, `keycloak-orgs`, `keycloak-atomic-auth-flows`. Several current
  references say "requires extension X" without saying how to install it. That gap is worth closing
  early.

  **Corrected: the hosted half of this is an API, not a skill.** Phase Two's control plane exposes
  full extension CRUD — `/clusters/{id}/extensions` (GET, POST, PUT, DELETE),
  `/extensions/keycloak-versions`, `/extensions/cluster-update` — so for a Phase Two cluster this is
  four Wave 1 tools (§4.2), not a reference file. What survives as a chapter is the **self-managed**
  path only: `kc.sh build`, the `providers/` directory, and which changes force a rebuild. That is
  genuinely not an API.
- **Case**: installing `keycloak-orgs` so the org-restrict intents work at all.
- **Outcome**: **split** — hosted → Wave 1 tools; self-managed → chapter in `keycloak-operations`.
- **Tooling**: cli, container, k8s (self-managed) · mcp (hosted) · **Deps**: stock

**J10 — Bootstrap admin and admin recovery**
- **What**: bootstrap admin credentials, temporary admin accounts, and recovering from a lost admin
  password.
- **Use when**: "locked out of the admin console", "forgot the admin password", "create the first
  admin", "temporary admin".
- **Problem**: a genuine emergency task with a documented, non-obvious procedure people otherwise
  solve by editing the database.
- **Case**: nobody can log into a production admin console.
- **Tooling**: cli · **Deps**: stock

**J11 — FIPS-compliant mode**
- **What**: running on a FIPS 140-2 validated cryptographic module, with its BouncyCastle and
  keystore constraints.
- **Use when**: "FIPS", "FedRAMP", "government compliance", "approved cryptography".
- **Problem**: narrow but hard-requirement audience; it constrains algorithm and keystore choices
  elsewhere (I3, F13), so it can't be bolted on later.
- **Case**: a federal customer requires FIPS mode.
- **Tooling**: cli · **Deps**: stock

---

### K. Deployment, high availability & observability

`docs/guides/high-availability` (59), `observability` (26), `operator` (7), `getting-started` (16),
`migration` (2), plus `documentation/upgrading` (59).

**K1 — Container deployment**
- **What**: the official image, optimized custom images (`kc.sh build` at image-build time),
  layering providers and themes, and container-appropriate configuration.
- **Use when**: "Dockerfile for Keycloak", "custom Keycloak image", "add my provider to the image",
  "slow startup".
- **Problem**: the optimized-image pattern (build at image time, `--optimized` at run time) is the
  difference between 5-second and 60-second startups and is the standard for anything serious.
- **Case**: baking `keycloak-orgs` and a theme into a deployable image.
- **Tooling**: container · **Deps**: stock

**K2 — Kubernetes with the Keycloak Operator**
- **What**: install the operator, the `Keycloak` and `KeycloakRealmImport` CRs, advanced
  configuration, unsupported/additional options.
- **Use when**: "Keycloak on Kubernetes", "operator", "Helm vs operator", "declare Keycloak as a
  CR", "realm import on startup".
- **Problem**: the recommended Kubernetes path, and the CR surface deliberately doesn't expose
  everything — knowing the escape hatch matters.
- **Case**: a platform team standardising Keycloak on EKS.
- **Tooling**: k8s · **Deps**: stock

**K3 — Operator rolling updates and update compatibility**
- **What**: the `Auto` update strategy, the `update-compatibility` command, and deciding
  rolling-vs-recreate in CI.
- **Use when**: "zero-downtime Keycloak upgrade", "rolling update", "can I upgrade without
  downtime", "GitOps upgrade check".
- **Problem**: new, scriptable, GitOps-friendly, and unknown — the alternative is guessing and
  taking an outage. Feature-flag changes in particular can force a recreate.
- **Case**: a CI pipeline that must decide its own deployment strategy per change.
- **Tooling**: cli, k8s · **Deps**: stock (26.x)

**K4 — Single-cluster HA deployment**
- **What**: the multi-node blueprint — sizing memory/CPU, thread and DB connection settings, load
  shedding, sticky sessions, verifying the deployment.
- **Use when**: "highly available Keycloak", "how many replicas", "sizing", "how much CPU does
  Keycloak need", "capacity planning".
- **Problem**: upstream ships actual formulas and tested-load numbers, which is far better than the
  guesses an agent would otherwise produce.
- **Case**: sizing for 500 logins/second.
- **Tooling**: k8s, cli · **Deps**: stock

**K5 — Multi-cluster / cross-DC deployment**
- **What**: the active-passive cross-site blueprint — external Infinispan cross-site, Aurora
  global database, an accelerator load balancer, and the site online/offline/synchronize runbooks.
- **Use when**: "multi-region Keycloak", "disaster recovery", "cross-DC", "active-passive", "fail
  over to another region".
- **Problem**: the most operationally complex thing in the product, with explicit runbooks that are
  far too intricate to reconstruct — and the guide is emphatic that active-active is not supported
  for all caches.
- **Case**: an RTO requirement spanning two AWS regions.
- **Tooling**: k8s, cli · **Deps**: stock

**K6 — Metrics and Prometheus/Grafana**
- **What**: enable metrics, the event-metrics feature, the published Grafana dashboards, histograms
  and exemplars.
- **Use when**: "monitor Keycloak", "Prometheus metrics", "Grafana dashboard for Keycloak",
  "alert on failed logins".
- **Problem**: upstream ships ready-made dashboards and defined SLIs; hand-rolling them is wasted
  work, and event metrics (login success/failure rates) are separately enabled.
- **Case**: an SRE team onboarding Keycloak into existing observability.
- **Tooling**: cli, k8s · **Deps**: stock

**K7 — Metrics-driven troubleshooting**
- **What**: the troubleshooting guides — which metric to look at for cache, database, clustering,
  HTTP, and JVM problems.
- **Use when**: "Keycloak is slow", "high latency on login", "database saturated", "cache misses",
  "why is Keycloak using so much memory".
- **Problem**: 11 doc files mapping symptom to metric — exactly the kind of lookup table an agent
  is good at applying and bad at inventing.
- **Case**: login latency spiked and nobody knows which layer.
- **Tooling**: cli · **Deps**: stock

**K8 — Distributed tracing (OpenTelemetry)**
- **What**: enable tracing, sampling configuration, and correlating spans with logs.
- **Use when**: "trace a login request", "OpenTelemetry", "Jaeger/Tempo", "where is the time going".
- **Problem**: newer capability, off by default; the only way to attribute latency inside a request
  rather than across requests.
- **Case**: a slow token endpoint with an unclear bottleneck.
- **Tooling**: cli · **Deps**: stock

**K9 — Version upgrades**
- **What**: reading the upgrade guide and release notes, the DB migration step, breaking-change
  triage, and rollback posture.
- **Use when**: "upgrade from 24 to 26", "breaking changes", "migration guide", "is it safe to
  upgrade", "deprecated in this version".
- **Problem**: 117 doc files of upgrade and release notes; the actual work is *finding the handful
  of changes that affect a given configuration*, which is a search-and-filter task an agent should
  do well with the right pointer.
- **Case**: a 24.x → 26.6 upgrade with custom providers and a custom theme.
- **Tooling**: cli · **Deps**: stock

**K10 — Local development environment**
- **What**: a fast, realistic local Keycloak — container, seeded realm, mail capture, and how to
  keep it close enough to production to be useful.
- **Use when**: "run Keycloak locally", "docker-compose for Keycloak", "test realm for
  development", "mailhog with Keycloak".
- **Problem**: every other skill needs somewhere to try things, and this repo's own benchmarks have
  already built exactly this environment — so it's cheap to write and reusable as the harness for
  verification runs.
- **Case**: a developer needing a working Keycloak in five minutes to test H5.
- **Tooling**: container · **Deps**: stock

---

### L. Extension & provider development

`server_development/*` (31 files). `adding-a-skill.md` §1 already names this category as needing its
own skill directory rather than the existing router — the work shape is writing and building Java,
not calling an API.

**L1 — Provider/SPI development fundamentals**
- **What**: the provider and factory model, `ProviderFactory` lifecycle, `KeycloakSession` scoping,
  service registration, JAR packaging, deployment into `providers/`, and configuration via
  `--spi-*`.
- **Use when**: "write a Keycloak extension", "custom SPI", "my provider isn't picked up",
  "Keycloak plugin development".
- **Problem**: the prerequisite for every other idea in this category; the registration and
  session-scoping rules are where first attempts fail (and fail at runtime, not at build time).
- **Case**: scaffolding a first extension against 26.6.
- **Tooling**: code · **Deps**: stock

**L2 — Custom authenticator**
- **What**: implement `Authenticator` and `AuthenticatorFactory` — the context API, config
  properties, required-action interaction, and FreeMarker form rendering.
- **Use when**: "custom login step", "authenticate against our internal service", "add a step to
  the login flow", "write an authenticator".
- **Problem**: the most-requested extension type, and how the p2-inc extensions this repo's skills
  already depend on (`ext-magic-form`, `ext-select-org`) are built — so it's also the skill that
  makes those understandable and forkable.
- **Case**: a login step that checks an internal allow-list API.
- **Tooling**: code · **Deps**: stock

**L3 — Custom protocol mapper**
- **What**: implement a mapper that injects computed claims into tokens.
- **Use when**: "custom claim from an external system", "computed claim", "the built-in mappers
  can't express this".
- **Problem**: the correct answer once F4's built-in mappers run out, and the second-most-common
  extension type.
- **Case**: a claim derived from a lookup in another database.
- **Tooling**: code · **Deps**: stock

**L4 — Custom user storage provider**
- **What**: `UserStorageProvider` and its capability interfaces, the import vs federated strategies,
  caching, paging, and the JPA/entity-manager options.
- **Use when**: "authenticate against our legacy database", "custom user federation", "REST-backed
  users", "gradual user migration".
- **Problem**: upstream's largest development sub-guide (17 files) because of the capability-
  interface matrix; also the honest destination for B5-adjacent requests that LDAP can't serve.
- **Case**: reading users from a legacy REST API during a two-year migration.
- **Tooling**: code · **Deps**: stock

**L5 — Custom event listener**
- **What**: implement `EventListenerProvider` for login and admin events, with attention to
  synchronous execution and failure handling.
- **Use when**: "webhook on login", "push events to Kafka", "audit to an external system", "react
  to user creation".
- **Problem**: the natural pair to I5, and the standard place people accidentally block the
  authentication path with a synchronous HTTP call.
- **Case**: publishing every registration to an internal event bus.
- **Tooling**: code · **Deps**: stock

**L6 — Custom REST endpoint (`RealmResourceProvider`)**
- **What**: add application-specific admin or public endpoints to Keycloak itself, with correct
  authentication and authorization.
- **Use when**: "add an API to Keycloak", "custom admin endpoint", "expose our own operation",
  "extend the Admin REST API".
- **Problem**: the mechanism behind extensions like `keycloak-atomic-auth-flows`'s
  `/authentication-flow/import` — which the existing skills already depend on — and the auth
  checks are easy to omit, producing an unauthenticated endpoint on the identity server.
- **Case**: a bulk operation the Admin API doesn't offer.
- **Tooling**: code · **Deps**: stock

**L7 — Custom required action**
- **What**: implement `RequiredActionProvider` for a mandatory step after authentication.
- **Use when**: "force users to accept a new policy", "collect a field on next login", "custom
  onboarding step".
- **Problem**: often confused with an authenticator — the distinction (before vs after
  authentication, and AIA-triggerable) determines which one is correct, and D3 is the config-side
  counterpart.
- **Case**: requiring acceptance of updated terms at next login.
- **Tooling**: code · **Deps**: stock

**L8 — Extending the data model and using the Admin Client**
- **What**: custom JPA entities with Liquibase changelogs, plus the `keycloak-admin-client` Java
  library for driving Keycloak from code.
- **Use when**: "store extra data in Keycloak's database", "custom table", "Java client for the
  Admin API", "programmatic realm setup in tests".
- **Problem**: custom schema is a genuine upgrade hazard (K9) and needs its own changelog
  discipline; the admin client is the right tool for I7-style automation from JVM code.
- **Case**: an extension needing its own persistent table.
- **Tooling**: code · **Deps**: stock

**L9 — Testing and debugging extensions**
- **What**: the Keycloak test framework, remote debugging a provider in a container, and iterating
  without a full rebuild.
- **Use when**: "test my authenticator", "debug a provider", "integration test for a Keycloak
  extension", "faster extension dev loop".
- **Problem**: without a loop, L2–L7 are guess-and-redeploy; and the rebuild requirement (J9) makes
  the naive loop very slow.
- **Case**: iterating on a custom authenticator's form handling.
- **Tooling**: code · **Deps**: stock

---

### M. Themes & UI customization

`docs/guides/ui-customization/*` (9 files).

**M1 — Theme basics and quick branding**
- **What**: theme types (login, account, admin, email, welcome), the inheritance chain, and the
  minimal "just change the logo and colours" path.
- **Use when**: "brand the login page", "custom logo", "change the colours", "white-label
  Keycloak".
- **Problem**: the most common customization request; upstream's quick-theme path avoids the
  full-theme rabbit hole most people fall into.
- **Case**: a company logo and palette on the login page.
- **Tooling**: code · **Deps**: stock

**M2 — Full custom login theme**
- **What**: FreeMarker templates, message bundles, static resources, and per-realm theme selection.
- **Use when**: "completely custom login page", "override the login template", "custom form
  fields", "restructure the login layout".
- **Problem**: overriding a template forks it — upgrade breakage (K9) is the predictable
  consequence, and the skill should say which overrides are cheap and which are expensive.
- **Case**: a login page matching a design system exactly.
- **Tooling**: code · **Deps**: stock

**M3 — React-based theming and custom console**
- **What**: the newer React theme approach and building a custom account or admin console against
  the Admin API.
- **Use when**: "React login page", "custom account console", "embed user management in our app",
  "our own admin UI".
- **Problem**: newer and less-known than FreeMarker; and "build your own console" is often the right
  answer to a request that would otherwise become an unmaintainable theme fork.
- **Case**: a product embedding user management in its own dashboard.
- **Tooling**: code, framework · **Deps**: stock

**M4 — Email templates**
- **What**: override the email theme's templates and subjects, HTML and plaintext, with locale
  variants.
- **Use when**: "brand the verification email", "change the magic-link email wording", "custom
  email template", "email in the user's language".
- **Problem**: directly downstream of A1/A2/A15/D2 — every email-based login feature immediately
  raises "can we make the email look like ours", and it's a *different* theme type from the login
  theme people are already editing.
- **Case**: a magic-link email carrying the customer's branding.
- **Tooling**: code · **Deps**: stock

**M5 — Localization and translation overrides**
- **What**: message bundles per locale, overriding individual keys, and realm-level translation
  overrides without a full theme.
- **Use when**: "translate the login page", "change one error message", "add a language",
  "reword a validation message".
- **Problem**: pairs with I9; the realm-level override path avoids a theme entirely for
  single-string changes, which is what most of these requests actually are.
- **Case**: rewording one confusing validation message.
- **Tooling**: rest, code · **Deps**: stock

---

### N. Phase Two platform

Phase Two SaaS control plane and the p2-inc extension catalogue. Two intents exist.

| # | Skill idea | Status |
|---|---|---|
| N1 | provision a Phase Two cluster | ✅ done |
| N2 | create a deployment (realm) in a cluster | ✅ done |

**N3 — Phase Two extension catalogue and selection**
- **What**: which p2-inc extensions exist, what each provides, what's bundled in Phase Two hosted
  vs. installable on self-managed — `keycloak-magic-link`, `keycloak-orgs`,
  `keycloak-atomic-auth-flows`, and the rest.
- **Use when**: "which Phase Two extension do I need", "is this available on self-hosted",
  "`ext-select-org` doesn't exist", "where does `ext-magic-form` come from".
- **Problem**: nine existing intents require a p2-inc extension, and a self-managed user following
  them today hits "authenticator not found" with no guidance on what to install. C4 covers the orgs
  half of this; this is the general version, and pairs with J9 for the install mechanics.

  **Corrected: the catalogue is queryable, so it should not be a hand-maintained document.**
  `GET /clusters/{id}/extensions` returns what is installed and
  `GET /extensions/keycloak-versions` what is compatible. A `listClusterExtensions` tool answers
  "which extension do I need / is it available here" against live state, where a written catalogue
  goes stale the moment the extension list changes.
- **Case**: a self-managed user asks for magic-link login on vanilla 26.6.
- **Outcome**: **tool gap** (Wave 1, §4.2). The residual prose — what each extension *provides* —
  belongs in the tool descriptions, per §4.2 rule 7.
- **Tooling**: mcp · **Deps**: p2 extensions

**N4 — Cluster operations (scale, upgrade, custom domain, backups)**
- **What**: the lifecycle of an existing Phase Two cluster beyond creation — tier changes, custom
  domains, version upgrades, and backup/restore.
- **Use when**: "add a custom domain", "upgrade my cluster", "scale up", "back up my Phase Two
  cluster".
- **Problem**: N1 stops at provisioning; everything after day one is uncovered, and this is what
  existing customers actually ask about.
- **Case**: pointing `auth.customer.com` at a Phase Two cluster.
- **Tooling**: mcp · **Deps**: p2-saas

**N5 — Migrating self-managed Keycloak to Phase Two (and back)**
- **What**: moving realms, users, and credentials between a self-hosted Keycloak and a Phase Two
  deployment, including what can't be moved.
- **Use when**: "migrate to Phase Two", "import my existing realm", "move off self-hosted", "export
  my data out".
- **Problem**: the onboarding path for every prospective customer, and it hits I6's export limits
  head-on (credentials, secrets, and flows all behave differently). Being straight about the exit
  path also matters commercially.
- **Case**: a team with a 3-year-old self-hosted realm evaluating Phase Two.
- **Tooling**: mcp, rest · **Deps**: p2-saas

**N6 — Phase Two MCP server setup and troubleshooting**
- **What**: connecting the Keycloak MCP server, authentication, which tools exist, and diagnosing
  connection or permission failures.
- **Use when**: "connect the Keycloak MCP server", "MCP tools aren't showing up", "401 from the MCP
  server", "which MCP tools are available".
- **Problem**: `mcp` is one of two tooling arms for **every** intent in the catalogue, so a broken
  MCP connection blocks half the skills — and there's nowhere to route that failure today. The
  reference conventions also require confirming live tool names before writing an MCP reference;
  this skill is where that check gets documented.
- **Case**: an agent's MCP tool calls fail and the developer can't tell whether it's auth, network,
  or a missing tool.
- **Tooling**: mcp · **Deps**: p2-saas

---

### O. Security hardening & compliance

`server_admin/topics/threat/*` (21 files), `clients/client-policies.adoc`, `securing-apps/dpop.adoc`,
`securing-apps/partials/oidc/{fapi,oauth21}-support.adoc`. Cross-cuts several categories, which is
why it's its own — the requests arrive as "make this secure/compliant", not as a config question.

**O1 — Security hardening checklist**
- **What**: work through upstream's threat-mitigation guide — SSL enforcement, brute force, host
  and redirect validation, clickjacking, CSRF, SSRF, open redirect, read-only attributes, scope and
  audience limits, admin endpoint exposure.
- **Use when**: "harden Keycloak", "security review", "penetration test findings", "is my Keycloak
  secure", "security checklist".
- **Problem**: 21 doc files of mitigations that are individually easy and collectively never all
  applied; several (read-only attributes, audience limits) close real vulnerabilities that nothing
  else surfaces.
- **Case**: a pentest report before launch.
- **Tooling**: rest, cli · **Deps**: stock

**O2 — FAPI compliance**
- **What**: apply the FAPI 1.0 Baseline/Advanced or FAPI 2.0 client profiles via client policies,
  and the constraints they impose.
- **Use when**: "FAPI", "open banking", "financial-grade API", "PAR and JARM required".
- **Problem**: a hard regulatory requirement with a precise checklist; Keycloak ships ready-made
  client profiles for it, so the work is applying them and understanding what they forbid — not
  hand-configuring 20 settings.
- **Case**: an open-banking deployment that must certify.
- **Tooling**: rest · **Deps**: stock

**O3 — OAuth 2.1 compliance**
- **What**: what OAuth 2.1 requires (PKCE everywhere, no implicit, exact redirect URIs, sender
  constraining) and how to enforce it with client policies.
- **Use when**: "OAuth 2.1", "modern OAuth best practice", "deprecate implicit flow", "require PKCE
  everywhere".
- **Problem**: the direction of travel, and a prerequisite for H12 (MCP's authorization spec
  *requires* OAuth 2.1) — so this is load-bearing for the most self-relevant skill in the catalogue.
- **Case**: bringing an existing realm's clients up to 2.1 before adding MCP support.
- **Tooling**: rest · **Deps**: stock

**O4 — DPoP / sender-constrained tokens**
- **What**: demonstrating proof-of-possession — binding a token to a client key so a stolen token
  is unusable, and the application-side proof generation.
- **Use when**: "sender-constrained tokens", "DPoP", "stop token replay", "bearer tokens are too
  risky", "mTLS-bound tokens".
- **Problem**: the strongest available answer to token theft, required at FAPI 2.0 and by MCP's
  newer specs, and needs coordinated server *and* client changes — half of it is application code.
- **Case**: a high-value API where bearer-token theft is unacceptable.
- **Tooling**: rest, framework · **Deps**: stock

**O5 — Admin console and admin API exposure**
- **What**: restricting or separating admin access — `hostname-admin`, network-level separation, and
  not exposing the admin endpoints publicly.
- **Use when**: "hide the admin console", "admin on a separate hostname", "restrict admin access",
  "should the admin console be public".
- **Problem**: upstream calls this out specifically (`threat/admin.adoc`); a publicly reachable
  admin console is a standard finding, and the fix spans J4's hostname options and infrastructure.
- **Case**: an internet-facing Keycloak whose admin console must be internal-only.
- **Tooling**: cli, k8s · **Deps**: stock

**O6 — Token and code compromise response**
- **What**: the incident playbook — revocation (F9), key rotation (I3), `not-before` pushes,
  session termination, and what genuinely cannot be recalled.
- **Use when**: "a token leaked", "signing key compromised", "security incident", "revoke
  everything", "force everyone to log in again".
- **Problem**: needs to be composed from four separate mechanisms under time pressure, and the
  honest limits (a live access token cannot be un-issued) must be stated rather than glossed.
- **Case**: a signing key found in a public repository.
- **Tooling**: rest, cli · **Deps**: stock

---

### P. Experimental / low priority

Listed for completeness, with a recommendation not to build yet.

**P1 — OID4VCI verifiable credential issuance** — `server_admin/topics/oid4vci/`. Upstream marks it
experimental with no backward-compatibility guarantee. A skill would encode an API that is expected
to break. Revisit when it leaves experimental.

**P2 — SPIFFE identity brokering** — `identity-broker/spiffe.adoc`. Very narrow (workload identity
in service meshes); build on demand.

**P3 — Kubernetes/OpenShift as an identity provider** — `identity-broker/kubernetes.adoc`. Narrow.

**P4 — SSSD user federation** — `user-federation/sssd.adoc`. Legacy relative to B5.

**P5 — Legacy SAML adapters and Galleon layers** — `securing-apps/saml-galleon-layers*.adoc`,
`mod-auth-mellon`. WildFly/JBoss-era integration; only worth writing for a customer who asks.

**P6 — Windows service installation** — `server/windows-service.adoc`. Rare.

---

## 5. Suggested build order

Two tracks, because §4 splits into two kinds of work. **Track A (tools) goes first** — it is cheaper
per item, it is where the measured win came from, and several Track B chapters get smaller once the
tools underneath them exist.

### Track A — tools, in `phasetwo-mcp`

**Wave 1** (§4.2) closes the most ideas per unit of work, and the corrections first:

1. **Fix the B5 / J9 / N3 factual errors.** `SKILL.md` currently refuses LDAP/AD as having no MCP
   tool while five exist. That is a live mis-route and lands independently of everything else here.
2. **`explainTokenClaims`** — answers "roles aren't in my token", the highest-traffic
   troubleshooting topic in the product, and closes parts of F4, E1 and C6 at once.
3. **Roles and groups** (E1, E2) — no tools at all today, and the most common admin surface after
   clients.
4. **Extension tools** (J9, N3 hosted) — retires this document's own Tier 1.
5. **User CRUD** (D4) and **`updateOidcClient`** (F1).

**Wave 2** then **Wave 3**, as listed in §4.2. Most Wave 1–2 tools need only a `@Tool` annotation
and a DTO, since `PUT /admin/realms/{realm}` and `PUT /clients/{id}` are already wired.

### Track B — chapters

1. **J9 self-managed extension install** — the residue of Tier 1 that is genuinely not an API, and
   nine shipped intents depend on it.
2. **J4** hostname & reverse proxy — the top real-world failure, and it pairs with `securing-apps`'
   token-validation content as one problem seen from two sides.
3. **A8** conditional MFA / step-up — the most misunderstood construct in Keycloak authentication,
   and a stock alternative to the extension-dependent MFA intents already shipped.
4. **B7** first-login & account linking — the complaint that follows every B3 rollout, and the one
   place the guidance has to refuse what is being asked for.
5. **O3** OAuth 2.1 → **H12** Keycloak as an MCP authorization server — self-relevant and verifiable
   against our own deployment.
6. **F6** standard vs legacy token exchange, **F10** offline & transient sessions.
7. Then `keycloak-extension-dev` — **L1–L9** plus **M2–M4** (theming folded in as a target-of-work
   match: both write source against Keycloak itself), narrower.

### Process notes

From `docs/skill-building-lessons.md`, with one addition:

- Every new chapter needs a benchmark with the oracle at reward 1.0 **and** a no-skill baseline. The
  baseline distinguishes "the skill works" from "the model could already do this." Both existing
  benchmarked tasks passed at 1.0 *without* the skill.
- Prefer **deliberate pairs** of benchmark tasks over one per capability. The same-component,
  opposite-configuration pair (passwordless vs password-gated OTP) is what revealed that skill value
  concentrates where there is a hidden trap.
- **New: benchmark at chapter level, not per idea, and measure the tool arm separately.** The
  previous draft's cost objection — 113 ideas × arms — dissolves once ~70 of those ideas are tools.
  But it is replaced by a sharper question: for anything in §4.2, the arm worth measuring is
  *with-tool*, not *with-prose*. The one measurement we have says a REST-prose arm scored 135 calls
  against a 126-call no-skill baseline. **If a prose arm ever materially beats its baseline on an
  operation-shaped task, §3's test is too strict and should be loosened** — so run that comparison
  once, on roles/groups, before committing to the whole of Track A.

Every new tool should also clear the four acceptance conditions that measurably drove agents off the
tool surface: surfaces the upstream error body, reports resolved rather than partial state, returns
`nextStep` where order matters, and says what it is *not*.

---

## 6. Open questions

**Resolved since the first draft** (see §3, §4):

1. ~~**Do we do the structural split now?**~~ **Yes, but into four skills, not fourteen and not
   six.** Most of the proposed category routers turned out to be tool gaps (§4.2); the two that
   remained separate in an earlier pass (`keycloak-hardening`, `keycloak-theming`) merge into
   `keycloak-operations` and `keycloak-extension-dev` respectively once the cut is made on **target
   of the work** — a live realm, your own application's source, the server process, or Keycloak's
   own source — rather than on Keycloak's documentation table of contents. The existing 13 intents
   all stay in the `keycloak` router, so the move is far smaller than "~24 file moves": reference
   files go into subdirectories, and the three new skill directories are created when their first
   chapter is written. This also retires the description-length argument as the split's
   justification — checked against a live `skillsaw lint` run, it was never the hard wall it was
   presented as (see the correction in §3); the real justification is target-of-work mismatch.
2. ~~**Scope of the repo — stock Keycloak or Phase Two?**~~ **Both, MCP-first.** Stock-Keycloak users
   are served by the **fallback REST column** in §4.2 rather than by paired prose files. This follows
   the measurement that REST-prose guidance bought nothing, and it means we stop writing
   `-mcp`/`-rest` pairs by default — a REST variant is written only where it carries a trap the MCP
   path does not remove.
5. ~~**Benchmark cost.**~~ Reframed in §5: benchmark at chapter level, and measure the *tool* arm
   rather than a prose arm for anything in §4.2.

**Still open:**

3. **Which Keycloak versions do we target?** Unchanged and still the sharpest gap. Several ideas
   (C5 organizations, D6–D8 workflows, E4 fine-grained v2, H12 MCP, K3 update-compatibility) are
   26.x-only, and pre-26 advice on hostname (J4) is actively wrong. References should state a minimum
   version; today none do. This now applies to **tool descriptions too** — a tool that silently
   assumes 26.6 semantics is the same failure in a worse place.
4. **Framework skills (H) are a different kind of work.** Answered in principle — they become the
   separate `securing-apps` skill with a `{framework}` axis rather than router intents — but whether
   ten of them belong in *this* repo is still a call to make.
7. **Who owns Track A?** ~55 tools is roughly a doubling of `phasetwo-mcp`: real Java work, in a
   different repo, on a different release cycle. The waves exist so this can stop after Wave 1 and
   still capture most of the value. **But if Track A is not resourced, the capabilities it covers end
   up served by nothing at all — which is worse than the first draft's position of promising prose.**
   This is the biggest risk in the document and needs an owner, not a recommendation.
8. **Does a ~160-tool surface have its own routing cost?** This document's objection to 132 competing
   skill descriptions applies in weaker form to tool schemas. Worth watching for tool-selection
   errors as Wave 1 lands, and preferring composite tools (`setTokenAndSessionTimeouts` over one tool
   per timeout field) where the fields genuinely interact.
9. **Is N6 (MCP setup/troubleshooting) a skill at all?** It has a real prerequisite problem — `mcp`
   is one of two tooling arms for everything — but its audience is a developer whose tools are
   failing, which argues for documentation on the MCP server rather than a skill loaded by an agent
   that cannot reach it.
