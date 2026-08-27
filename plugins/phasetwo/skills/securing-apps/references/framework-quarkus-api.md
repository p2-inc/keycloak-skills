# Quarkus — bearer-JWT resource server where `quarkus-oidc` already understands Keycloak's roles

## What this is

Wiring for a Quarkus service that accepts `Authorization: Bearer <jwt>`, verifies it against your
realm's JWKS, and grants `@RolesAllowed`. Quarkus is the odd one out in this set: `quarkus-oidc`
reads Keycloak's nested role claims **natively**, so there is no converter to write. What this file
mostly does is tell you the three ways that automatic behaviour silently stops applying.

No login UI, no session cookie, no redirect. If the same app also serves pages and logs users in,
that is `application-type=hybrid` and `app:add-login`, not this file.

**Verified 2026-08-27 against Quarkus 3.39.1** (latest release of `io.quarkus.platform:quarkus-bom`
and `io.quarkus:quarkus-oidc`). Property names, defaults, and the role-resolution order below were
read from the `quarkus-oidc` 3.39.1 sources — `OidcTenantConfig` and `OidcUtils.findRoles` — not from
memory or from a blog.

The rules that are identical in every language — issuer matching, `aud` vs `azp`, JWKS caching and
rotation, algorithm pinning, clock skew, local verification vs introspection — live in
[pattern-token-validation.md](pattern-token-validation.md). Read it alongside this file. Nothing
there is repeated here.

---

## There was never a Keycloak Quarkus adapter

Keycloak never shipped a Quarkus adapter, so there is nothing removed or deprecated to migrate off.
`quarkus-oidc` is a Quarkus extension, maintained by the Quarkus team, and it is the supported
answer. (Keycloak itself has been *built* on Quarkus since version 17, which is a different thing
entirely and not relevant here.)

| If you see this in the project | Note |
|---|---|
| `quarkus-oidc` | correct; this file |
| `quarkus-smallrye-jwt` | verifies JWTs generically via MicroProfile JWT. Works, but knows nothing about `realm_access` — you would map roles by hand via `groups`. Prefer `quarkus-oidc` against Keycloak. |
| `quarkus-keycloak-authorization` | an **addition** to `quarkus-oidc`, described upstream as a *"Policy enforcer using Keycloak-managed permissions to control access to protected resources"*. Not needed for plain role checks; do not add it just to get roles. |
| `org.keycloak:keycloak-*-adapter` | Java adapters, removed in Keycloak 25.0.0 |

---

## Step 1: The dependency

```bash
quarkus extension add oidc
```

or, without the CLI:

```bash
./mvnw quarkus:add-extension -Dextensions='oidc'
```

Either writes this into `pom.xml`:

```xml
<dependency>
  <groupId>io.quarkus</groupId>
  <artifactId>quarkus-oidc</artifactId>
</dependency>
```

Gradle:

```kotlin
implementation("io.quarkus:quarkus-oidc")
```

**No `<version>`.** The version comes from `io.quarkus.platform:quarkus-bom`, which your project
already imports. Pinning `quarkus-oidc` by hand is how you get an extension that does not match your
Quarkus core and fails at augmentation time with a confusing build error.

`quarkus-oidc` pulls in `quarkus-security` transitively, so `@RolesAllowed` works without adding
anything else.

---

## Step 2: The configuration

`src/main/resources/application.properties`:

```properties
quarkus.oidc.auth-server-url=https://auth.example.com/realms/acme
quarkus.oidc.client-id=my-api
quarkus.oidc.application-type=service
quarkus.oidc.token.audience=my-api
```

`auth-server-url` is your realm's base URL — scheme, host, port, `/realms/<realm>`, **no trailing
slash**. Replace `auth.example.com` with your Keycloak hostname and `acme` with your realm name. On
Phase Two this is the `issuer` returned by `createOidcClient`. Quarkus appends
`/.well-known/openid-configuration` and discovers everything else — JWKS URI, issuer, endpoints.

What each property is actually doing:

| Property | Verified default | Why it appears here |
|---|---|---|
| `quarkus.oidc.auth-server-url` | none, required | discovery root |
| `quarkus.oidc.client-id` | none | **not required for `service`** — but omitting it silently disables client-role mapping. See Step 3. |
| `quarkus.oidc.application-type` | `service` | already the default; state it so nobody later assumes `web-app` and gets redirects |
| `quarkus.oidc.token.audience` | none — **`aud` unchecked on access tokens if omitted** | the check everyone skips; see below |
| `quarkus.oidc.token.issuer` | falls back to the discovered `issuer` | leave unset. Setting it **overrides** discovery; setting it to `any` **disables** issuer verification. |
| `quarkus.oidc.token.signature-algorithm` | provider-driven | only set it to pin harder than the realm's metadata |
| `quarkus.oidc.token.principal-claim` | checks `upn`, `preferred_username`, `sub` | set it deterministically — but treat the principal name as **display only** and key authorization on `sub` (see [pattern-token-validation.md](pattern-token-validation.md)) |
| `quarkus.oidc.discovery-enabled` | `true` | leave on; turning it off means configuring every endpoint by hand |
| `quarkus.oidc.jwks.cache-time-to-live` | `10M` | JWKS cache TTL |
| `quarkus.oidc.jwks.cache-size` | `10` | cached key count |
| `quarkus.oidc.jwks.resolve-early` | `true` | fetch keys at startup — see the startup note below |
| `quarkus.oidc.tls.tls-configuration-name` | none | names a `quarkus.tls.<name>.*` config for a private CA |
| `quarkus.oidc.credentials.secret` | none | **not needed for bearer validation** — only for introspection or outbound calls |

### `application-type=service` is already the default

Verified: `applicationType()` is annotated `@ConfigDocDefault("service")`. Declaring it costs nothing
and prevents the most confusing Quarkus-OIDC failure — a bearer API accidentally configured as
`web-app`, which responds to a missing token with a **302 redirect to the Keycloak login page**
instead of a 401. An API client follows the redirect, gets HTML, and reports "the API returned a
login page".

### No client secret is needed

A resource server validating JWTs locally never calls Keycloak's token or introspection endpoint, so
it needs no credential. `quarkus.oidc.credentials.secret` is only required if you enable
introspection (opaque tokens) or the service also acts as an OIDC client. Adding a secret you do not
need is one more thing to leak.

### `resolve-early` makes Keycloak a startup dependency

With `quarkus.oidc.jwks.resolve-early=true` (the default) Quarkus fetches the JWKS during startup. If
Keycloak is unreachable, **the application fails to start** rather than starting degraded. In Docker
Compose or Kubernetes that shows up as a boot-order crash loop, not a runtime 401. Setting it to
`false` defers the first fetch to the first request — which trades a startup failure for a slower
first request, and is usually the right trade in a cluster with no ordering guarantees.

### Audience

Verified from `OidcTenantConfig.Token.audience()`: *"Audience verification for access tokens is only
done if this property is configured."* So `aud` on a bearer access token is **not checked by
default** — that is exactly the gap described in
[pattern-token-validation.md](pattern-token-validation.md).

But Keycloak does not put a useful `aud` in access tokens by default either; you need an audience
mapper on the client, which is realm configuration and belongs to the `keycloak` skill. Setting
`quarkus.oidc.token.audience=my-api` before that mapper exists rejects **every** token. Add the
mapper first, then the property. `quarkus.oidc.token.audience=any` explicitly skips the check — it is
a real, supported value, and it is the wrong answer to a rejection you have not diagnosed.

There is no `azp` setting; if you need the `azp` fallback, use `quarkus.oidc.token.required-claims`:

```properties
quarkus.oidc.token.required-claims.azp=my-web-app,my-mobile-app
```

Verified semantics, and they are not what you would guess: a comma-separated value requires the claim
to have **all** listed values, not any of them. For a single-valued claim like `azp` that means a
list here can never match. Use one value, or augment the identity in code.

---

## Step 3: Roles — what is automatic, and the three ways it stops being automatic

**`quarkus-oidc` already reads Keycloak's nested role claims.** This is the one framework in this set
where the default converter is not wrong. `@RolesAllowed("admin")` matches a Keycloak realm role
`admin` with no configuration and no code.

There is also **no `ROLE_` prefix** in Quarkus. The role name in the token is the role name in the
annotation. (If you are coming from Spring, this is the difference that trips people.)

Verified from `OidcUtils.findRoles(clientId, rolesConfig, json)` in 3.39.1, this is the exact
resolution order:

| Order | Quarkus looks at | And then |
|---|---|---|
| 1 | `quarkus.oidc.roles.role-claim-path`, if set | uses **only** those paths and stops. Nothing below runs. |
| 2 | the `groups` claim | if it is **non-empty**, returns it and stops |
| 3 | `realm_access/roles` | always added |
| 3 | `resource_access/{quarkus.oidc.client-id}/roles` | added **only if `client-id` is set** |

Three consequences, each of which is a real bug that looks like something else:

**(a) Setting `role-claim-path` turns the Keycloak defaults OFF.** It is not additive. The moment you
set it to pick up one extra claim, `realm_access/roles` stops being consulted unless you list it
yourself. Every realm role vanishes and `@RolesAllowed` denies across the board. If you set the
property at all, list every path you want:

```properties
quarkus.oidc.roles.role-claim-path=realm_access/roles,resource_access/my-api/roles
```

Paths are `/`-separated segments from the top of the JWT. The splitter is
`Pattern.compile("\\/(?=(?:(?:[^\"]*\"){2})*[^\"]*$)")` — it splits on `/` **outside double
quotes** — so a claim name that itself contains `/` or a namespace-qualified name is written in
double quotes: `"https://example.com/roles"/list`.

**(b) A non-empty `groups` claim shadows Keycloak's roles entirely.** If someone adds a `groups`
mapper to the client — a very common thing to do for other reasons — Quarkus returns the groups and
never looks at `realm_access`. Your realm roles disappear with no error and no log line. If roles
stop working right after a realm change, check for a `groups` claim in the token first.

**(c) Client roles need `quarkus.oidc.client-id`.** `resource_access` is keyed by client ID, and
Quarkus uses `client-id` as that key. It is documented as *not required* for `service` applications —
which is true for authentication and false for authorization. Leave it out and `resource_access` is
never read: realm roles work, client roles are silently absent. Set it.

Related: `quarkus.oidc.roles.role-claim-separator` (default: a single space) only applies when a
role claim holds a **string** rather than an array — it is how the space-separated `scope` claim would
be split. Keycloak's role claims are arrays, so it does not apply, and setting it will not fix an
empty role list.

And `quarkus.oidc.roles.source` defaults to `accesstoken` for `service` applications — which is what
you want for a bearer API. Changing it to `idtoken` on a service that never receives an ID token
yields no roles at all.

---

## Step 4: Use the roles

```java
package com.example.api;

import jakarta.annotation.security.RolesAllowed;
import jakarta.inject.Inject;
import jakarta.ws.rs.DELETE;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.PathParam;

import org.eclipse.microprofile.jwt.JsonWebToken;
import io.quarkus.security.identity.SecurityIdentity;

@Path("/api/reports")
public class ReportResource {

    @Inject
    SecurityIdentity identity;

    @Inject
    JsonWebToken jwt;          // the VERIFIED token

    @GET
    @RolesAllowed("reader")
    public List<Report> list() {
        // Scope by `sub`, not `preferred_username`: a username can be changed by an
        // admin and a freed one reassigned, so username-keyed lookups silently resolve
        // to the wrong person. See pattern-token-validation.md.
        return service.forUser(jwt.getClaim("sub"));
    }

    @DELETE
    @Path("/{id}")
    @RolesAllowed({ "admin", "editor" })
    public void delete(@PathParam("id") String id) { ... }

    @GET
    @Path("/whoami")
    @RolesAllowed("**")        // any authenticated caller
    public Map<String, Object> whoami() {
        return Map.of(
            "name", identity.getPrincipal().getName(),
            "roles", identity.getRoles());
    }
}
```

`@RolesAllowed("**")` means "any authenticated identity" — it is a Quarkus-specific value, not a
wildcard role name. `@PermitAll` means genuinely open.

To require authentication on everything without annotating each resource:

```properties
quarkus.http.auth.permission.authenticated.paths=/api/*
quarkus.http.auth.permission.authenticated.policy=authenticated
```

Prefer this over per-method annotations for the "is a token required at all" question. An endpoint
with **no** annotation and no path policy is open — Quarkus does not deny by default, and a new
resource class added later inherits that openness silently.

---

## Verify

**1. The application starts.** With `resolve-early=true` (default), a failure to reach Keycloak
shows up here, naming the URL. That is the fastest signal that `auth-server-url` is wrong.

**2. No token is rejected:**

```bash
curl -i http://localhost:8080/api/reports
# expect: HTTP/1.1 401
```

If you get **302** with a `Location:` pointing at Keycloak, `application-type` resolved to `web-app`.
That is Step 2.

**3. A real token is accepted:**

```bash
TOKEN=$(curl -s -d 'client_id=my-api' -d 'client_secret=…' -d 'grant_type=client_credentials' \
  https://auth.example.com/realms/acme/protocol/openid-connect/token | jq -r .access_token)

curl -i -H "Authorization: Bearer $TOKEN" http://localhost:8080/api/reports
```

**4. Confirm which roles Quarkus actually resolved.** This is the check that separates "the token has
no roles" from "Quarkus did not look where the roles are":

```bash
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8080/api/reports/whoami | jq
```

`identity.getRoles()` is the resolved set, after all four resolution steps above. Compare it against
what is actually in the token:

```bash
echo "$TOKEN" | cut -d. -f2 | base64 -d 2>/dev/null | jq '{iss, aud, azp, groups, realm_access, resource_access}'
```

- Roles in `realm_access.roles` but `getRoles()` empty → resolution problem. Check for a `groups`
  claim, and check whether `role-claim-path` is set.
- `realm_access` absent from the token → role-mapper problem in the realm, which is the `keycloak`
  skill's territory. Stop editing `application.properties`.

**5. Turn on the log that tells you why**, temporarily:

```properties
quarkus.log.category."io.quarkus.oidc".level=DEBUG
quarkus.log.category."io.quarkus.oidc.runtime".level=TRACE
```

`TRACE` on `io.quarkus.oidc.runtime` prints the verification failure reason and the roles it
resolved. Take it back out before production — it logs claim contents.

**6. Dev Services will hide a broken config.** In dev mode Quarkus may start its own Keycloak
container and point the app at it, so everything passes locally against a realm that is not yours.
Prefix real config with `%prod.` or set `quarkus.keycloak.devservices.enabled=false` before you
conclude the wiring is correct.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| **302 redirect to the Keycloak login page instead of 401** | `application-type` resolved to `web-app` | set `quarkus.oidc.application-type=service` |
| **403 with realm roles clearly in the token** | `quarkus.oidc.roles.role-claim-path` is set, which **disables** the Keycloak defaults | list every path explicitly, or remove the property |
| **403, and the token has a `groups` claim** | a non-empty `groups` shadows `realm_access` entirely | remove the `groups` mapper, or list both paths in `role-claim-path` |
| **Realm roles work, client roles do not** | `quarkus.oidc.client-id` unset, so `resource_access` is never read | set `quarkus.oidc.client-id` to this API's client id |
| **403 on every role, `getRoles()` empty** | `quarkus.oidc.roles.source` pointed at `idtoken` on a bearer service | remove it; `accesstoken` is the default for `service` |
| 401, "Invalid audience" or similar after adding audience config | `quarkus.oidc.token.audience` set but no audience mapper on the client | add the mapper in Keycloak; do not "fix" it with `audience=any` |
| 401 on every request | issuer mismatch — usually Keycloak behind a proxy issuing its internal hostname | fix Keycloak's hostname config, not the API; see [pattern-token-validation.md](pattern-token-validation.md) |
| 401 after some minutes | expired, or host clock drift | check NTP |
| **App fails to start**, cannot reach the OIDC server | `resolve-early=true` and Keycloak unreachable | fix the URL/network, or set `quarkus.oidc.jwks.resolve-early=false` to defer |
| Startup failure with `PKIX path building failed` | Keycloak behind a private CA | set `quarkus.oidc.tls.tls-configuration-name` to a configured `quarkus.tls.<name>.*`; **never** disable verification |
| Works in dev, 401 in prod | Dev Services silently substituted its own Keycloak | prefix real config with `%prod.`, or `quarkus.keycloak.devservices.enabled=false` |
| An endpoint is reachable with no token | no annotation and no path policy — Quarkus does not deny by default | add `@RolesAllowed`/`@Authenticated`, or a `quarkus.http.auth.permission.*` policy |
| `@RolesAllowed("ROLE_admin")` never matches | Quarkus adds no prefix | use the bare role name: `@RolesAllowed("admin")` |
| `role-claim-separator` set, still no roles | it only applies to **string-valued** claims; Keycloak's are arrays | remove it and fix the path instead |
| Build fails after pinning `quarkus-oidc` | extension version diverged from the platform BOM | drop the `<version>`; let `quarkus-bom` manage it |
