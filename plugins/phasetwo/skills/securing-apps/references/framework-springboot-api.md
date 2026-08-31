<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# Spring Boot — bearer-JWT resource server, with Keycloak roles mapped to Spring authorities

## What this is

Wiring for a Spring Boot service that accepts `Authorization: Bearer <jwt>`, verifies the token
against your realm's JWKS, and converts Keycloak's roles into Spring Security authorities so
`hasRole(...)` and `@PreAuthorize` actually grant access.

No login UI, no cookie session, no redirect. If the same app also logs users in from a browser, that
is `app:add-login`, not this file.

**Verified 2026-08-27 against Spring Boot 4.1.1 (latest GA) and 3.5.16 (latest 3.x GA), Spring
Security 7.1.1.** Property names and defaults below were read out of
`spring-boot-security-oauth2-resource-server-4.1.1.jar` (`META-INF/spring-configuration-metadata.json`)
and the Spring Security 7.1.1 sources, not from memory.

The rules that are identical in every language — issuer matching, `aud` vs `azp`, JWKS caching and
rotation, algorithm pinning, clock skew, local verification vs introspection — live in
[pattern-token-validation.md](pattern-token-validation.md). Read it alongside this file. Nothing
there is repeated here.

---

## It replaces `keycloak-spring-boot-starter`, which no longer exists

`org.keycloak:keycloak-spring-boot-starter` and `keycloak-spring-security-adapter` were **removed in
Keycloak 25.0.0**. They are not deprecated-but-working; they are gone from the release. A `pom.xml`
that asks for them fails to resolve against any current Keycloak version, and `KeycloakWebSecurityConfigurerAdapter`
does not compile against Spring Security 6 or 7 regardless.

There is no Keycloak-supplied replacement and there does not need to be. Spring Security's own
resource server support speaks plain OIDC, which is all Keycloak issues.

| If you see this in the project | It is | Do this |
|---|---|---|
| `keycloak-spring-boot-starter`, `keycloak-spring-security-adapter` | removed in Keycloak 25.0.0 | delete it; follow this file |
| `KeycloakWebSecurityConfigurerAdapter`, `KeycloakAuthenticationProvider` | from the removed adapter | delete it; use the `SecurityFilterChain` bean below |
| `keycloak.realm` / `keycloak.auth-server-url` / `keycloak.resource` in `application.yml` | the removed adapter's config keys | replace with `spring.security.oauth2.resourceserver.*` |
| `WebSecurityConfigurerAdapter` (no Keycloak prefix) | removed in Spring Security 6.0 | rewrite as a `SecurityFilterChain` bean |

---

## Step 1: The dependency

Spring Boot 4.0 **renamed** this starter. The old artifact still publishes and still works, but its
own POM now carries the deprecation in its `<description>`: *"Starter for using Spring Security's
OAuth2 resource server features (deprecated in favor of spring-boot-starter-security-oauth2-resource-server)"*.
Both artifacts resolve to the identical three dependencies in 4.1.1.

| Spring Boot | Artifact (`org.springframework.boot`) |
|---|---|
| **4.0 and later** | `spring-boot-starter-security-oauth2-resource-server` |
| **3.x** | `spring-boot-starter-oauth2-resource-server` — the new name does not exist before 4.0.0-M1 |

Pick by the Boot version in the project, not by preference. Using the new name on Boot 3.x fails to
resolve; using the old name on Boot 4.x builds fine but will break on a future major.

**Maven — Boot 4.x:**

```xml
<dependency>
  <groupId>org.springframework.boot</groupId>
  <artifactId>spring-boot-starter-security-oauth2-resource-server</artifactId>
</dependency>
```

**Maven — Boot 3.x:**

```xml
<dependency>
  <groupId>org.springframework.boot</groupId>
  <artifactId>spring-boot-starter-oauth2-resource-server</artifactId>
</dependency>
```

**Gradle — Boot 4.x:**

```kotlin
implementation("org.springframework.boot:spring-boot-starter-security-oauth2-resource-server")
```

No `<version>`: the `spring-boot-starter-parent` / dependency-management plugin supplies it. Pinning
a version by hand is how you end up with a Spring Security jar that does not match your Boot version.

Spring Boot 4.x requires **Java 17 or later** (its class files are major version 61).

---

## Step 2: The configuration

Two properties. That is the whole of it.

**`application.yml`:**

```yaml
spring:
  security:
    oauth2:
      resourceserver:
        jwt:
          issuer-uri: https://auth.example.com/realms/acme
          audiences:
            - my-api
```

**`application.properties`:**

```properties
spring.security.oauth2.resourceserver.jwt.issuer-uri=https://auth.example.com/realms/acme
spring.security.oauth2.resourceserver.jwt.audiences=my-api
```

`issuer-uri` is your realm's issuer — scheme, host, port, path, realm name, **no trailing slash**.
Replace `auth.example.com` with your Keycloak hostname and `acme` with your realm name. On Phase Two
this is the `issuer` returned by `createOidcClient`. Boot fetches
`{issuer-uri}/.well-known/openid-configuration` **at startup**, reads `jwks_uri` from it, and builds
a caching `JwtDecoder`. `my-api` is your API's audience value; see the audience note below.

Every `spring.security.oauth2.resourceserver.jwt.*` property that exists, verified from the 4.1.1
configuration metadata:

| Property | What it does | Note |
|---|---|---|
| `issuer-uri` | discovery endpoint; sets both the JWKS URI and the expected `iss` | prefer this over `jwk-set-uri` |
| `jwk-set-uri` | JWKS URL directly, skipping discovery | **does not validate `iss` on its own** — see below |
| `audiences` | list of accepted `aud` values | off unless you set it |
| `jws-algorithms` | accepted signature algorithms | defaults to `RS256`; leave it |
| `principal-claim-name` | which claim becomes `Authentication.getName()` | `preferred_username` reads well in logs, but it is **mutable** — never authorize on `getName()`; key ownership checks on `sub` (see [pattern-token-validation.md](pattern-token-validation.md)) |
| `authorities-claim-name` | flat claim to read authorities from | **useless for Keycloak roles** — they are nested |
| `authorities-claim-delimiter` | regex splitting a string-valued authorities claim | mutually exclusive with `authorities-claim-expressions` |
| `authority-prefix` | prefix on mapped authorities | default `SCOPE_`; you want `ROLE_` |
| `authorities-claim-expressions` | **Boot 4.x only** — SpEL paths into nested claims | see Step 3, Option B |
| `public-key-location` | a static public key file | never do this against Keycloak; it breaks at the first key rotation |

### `jwk-set-uri` does not check the issuer

If you set `jwk-set-uri` instead of `issuer-uri`, Boot builds a decoder that verifies the signature
but **does not validate `iss`**, because it was never told what the issuer should be. A token from
any realm sharing those signing keys is then accepted. Use `issuer-uri`. Only reach for `jwk-set-uri`
when the discovery document is genuinely unreachable from the API, and then add an issuer validator
by hand.

### `issuer-uri` is resolved at startup

Boot calls the discovery endpoint while the context is building. If Keycloak is down or not yet
reachable, **the application fails to start** rather than starting degraded. In Docker Compose or
Kubernetes that shows up as a boot-order crash loop, not a runtime 401. If you need lazy resolution,
declare your own `JwtDecoder` bean built with
`JwtDecoders.fromIssuerLocation(...)` behind a lazy supplier, or make Keycloak a startup dependency.

### Audience

Keycloak does not put a useful `aud` in access tokens by default — you need an audience mapper on the
client, which is realm configuration and belongs to the `keycloak` skill. Setting `audiences: [my-api]`
before that mapper exists rejects **every** token with `An error occurred while attempting to decode
the Jwt: The aud claim is not valid`. Add the mapper first, then the property. The reasoning, and the
`azp` fallback when you cannot add a mapper, is in
[pattern-token-validation.md](pattern-token-validation.md).

---

## Step 3: The role converter — the part everything else depends on

**This is why this file exists.** Spring Security's default `JwtGrantedAuthoritiesConverter` reads
the `scope` or `scp` claim (verified: `WELL_KNOWN_AUTHORITIES_CLAIM_NAMES = ["scope", "scp"]`) and
prefixes each value with `SCOPE_` (verified: `DEFAULT_AUTHORITY_PREFIX = "SCOPE_"`).

Keycloak does not put roles there. It puts them in `realm_access.roles` and
`resource_access.<client-id>.roles`.

So out of the box, against a perfectly valid Keycloak token, you get authorities like
`SCOPE_profile`, `SCOPE_email` — and `hasRole("admin")` denies. The token verifies. The user is
authenticated. Every authorization check fails. That is a 403 on a good token, and it is the single
most common Keycloak-plus-Spring bug.

`hasRole("admin")` looks for the authority `ROLE_admin`. The `ROLE_` prefix is not optional and not
cosmetic — `hasRole` adds it, `hasAuthority` does not.

### Option A: the converter bean — works on Boot 3.x and 4.x

Prefer this. It is portable across both Boot generations, it is testable, and a typo in it is a
compile error rather than a silent empty list.

```java
package com.example.api.security;

import java.util.Collection;
import java.util.List;
import java.util.Map;

import org.springframework.core.convert.converter.Converter;
import org.springframework.security.core.GrantedAuthority;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.oauth2.jwt.Jwt;

/**
 * Maps Keycloak's realm_access.roles into ROLE_-prefixed Spring authorities.
 */
public final class KeycloakRealmRoleConverter implements Converter<Jwt, Collection<GrantedAuthority>> {

    @Override
    public Collection<GrantedAuthority> convert(Jwt jwt) {
        Map<String, Object> realmAccess = jwt.getClaimAsMap("realm_access");
        if (realmAccess == null) {
            return List.of();
        }
        if (!(realmAccess.get("roles") instanceof Collection<?> roles)) {
            return List.of();
        }
        return roles.stream()
                .map(String::valueOf)
                .map(role -> (GrantedAuthority) new SimpleGrantedAuthority("ROLE_" + role))
                .toList();
    }
}
```

`getClaimAsMap` is `org.springframework.security.oauth2.core.ClaimAccessor.getClaimAsMap(String)`,
which `Jwt` inherits. It returns `null` — not an empty map — for an absent claim, which is why the
null check comes first. Returning `List.of()` rather than throwing is deliberate: a user with no
realm roles is a legitimate authenticated user with zero authorities, not an authentication failure.

Then wire it into the filter chain. **`SecurityFilterChain` bean style — `WebSecurityConfigurerAdapter`
was removed in Spring Security 6.0 and does not exist in 7.x:**

```java
package com.example.api.security;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.config.annotation.method.configuration.EnableMethodSecurity;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationConverter;
import org.springframework.security.web.SecurityFilterChain;

@Configuration
@EnableWebSecurity
@EnableMethodSecurity
public class ResourceServerConfig {

    @Bean
    JwtAuthenticationConverter jwtAuthenticationConverter() {
        JwtAuthenticationConverter converter = new JwtAuthenticationConverter();
        converter.setJwtGrantedAuthoritiesConverter(new KeycloakRealmRoleConverter());
        // Display/logging only — `preferred_username` is mutable, so authorization
        // and ownership checks must key on `sub`.
        converter.setPrincipalClaimName("preferred_username");
        return converter;
    }

    @Bean
    SecurityFilterChain apiFilterChain(HttpSecurity http, JwtAuthenticationConverter converter) throws Exception {
        http
            .authorizeHttpRequests(auth -> auth
                .requestMatchers("/actuator/health/**").permitAll()
                .requestMatchers("/api/admin/**").hasRole("admin")
                .anyRequest().authenticated()
            )
            .oauth2ResourceServer(oauth2 -> oauth2
                .jwt(jwt -> jwt.jwtAuthenticationConverter(converter))
            )
            .sessionManagement(session -> session
                .sessionCreationPolicy(SessionCreationPolicy.STATELESS)
            )
            .csrf(csrf -> csrf.disable());
        return http.build();
    }
}
```

Three things in that chain are load-bearing:

- **`SessionCreationPolicy.STATELESS`.** Without it Spring creates an `HttpSession` per request and
  hands back a `JSESSIONID`. A bearer API does not need it, and it turns a stateless service into one
  that cannot be scaled without sticky sessions or session replication.
- **`csrf.disable()`.** CSRF protection defends cookie-borne credentials. A token in an
  `Authorization` header is not sent automatically by the browser, so there is nothing to forge —
  but leaving CSRF on makes every `POST` fail with a 403 and no useful message. Disable it **only**
  because this chain is stateless and bearer-only; if the same app also has a cookie-session chain,
  that chain keeps CSRF.
- **`@EnableMethodSecurity`** is what makes `@PreAuthorize` work. Without it the annotations are
  inert — they are silently ignored, and the endpoint is open to any authenticated caller. It is on
  by default in a Boot app with method security auto-configuration present, but declare it explicitly
  so its absence cannot be mistaken for a default.

Declaring a `JwtAuthenticationConverter` bean also makes Boot's own property-driven converter back
off — its auto-configuration is `@ConditionalOnMissingBean(JwtAuthenticationConverter.class)`. So
Option A and Option B do not fight; the bean wins.

### Option B: `authorities-claim-expressions` — Boot 4.x only, no Java

Spring Boot 4.0 added a property that does the nesting for you. **It does not exist in Boot 3.x** —
it is absent from the 3.5.16 configuration metadata, so on 3.x it binds to nothing and is silently
ignored, leaving you back at `SCOPE_`.

```yaml
spring:
  security:
    oauth2:
      resourceserver:
        jwt:
          authority-prefix: "ROLE_"
          authorities-claim-expressions:
            - "['realm_access']['roles']"
            - "['resource_access']['my-api']['roles']"
```

Or in `application.properties`:

```properties
spring.security.oauth2.resourceserver.jwt.authority-prefix=ROLE_
spring.security.oauth2.resourceserver.jwt.authorities-claim-expressions[0]=['realm_access']['roles']
spring.security.oauth2.resourceserver.jwt.authorities-claim-expressions[1]=['resource_access']['my-api']['roles']
```

Five things about this that will otherwise cost you an afternoon:

- **In YAML the expression must be quoted.** A scalar starting with `[` is a YAML flow sequence.
  Unquoted, `- ['realm_access']['roles']` is a YAML parse error, not a Spring error.
- **The SpEL root object is the claims map, not the `Jwt`.** Verified: `ExpressionJwtGrantedAuthoritiesConverter`
  calls `expression.getValue(jwt.getClaims(), Collection.class)`. So the expression indexes straight
  into claims — `['realm_access']['roles']`, never `claims['realm_access']` and never `getClaims()`.
- **Set `authority-prefix: ROLE_` explicitly.** `ExpressionJwtGrantedAuthoritiesConverter` also
  defaults to `SCOPE_`, and Boot only overrides it when the property is non-null. Omit it and
  `hasRole` still denies, which looks exactly like the bug you were fixing.
- **A wrong expression fails silently.** `ExpressionJwtGrantedAuthoritiesConverter` catches
  `ExpressionException` and returns an empty list. A typo in a claim name produces zero authorities
  and zero log output above `TRACE` — indistinguishable from a user who genuinely has no roles.
- **The prefix is shared across all expressions.** Realm roles and client roles both get `ROLE_`, so
  a realm role `admin` and a client role `admin` collapse into the same authority. If you need them
  distinguished, use Option A.

`authorities-claim-expressions` is mutually exclusive with both `authorities-claim-name` and
`authorities-claim-delimiter`; setting them together throws
`MutuallyExclusiveConfigurationPropertiesException` at startup.

### Client roles instead of realm roles

`resource_access` is keyed by client ID, and that key is your API's client ID — a literal string, not
something Spring knows. Extend Option A:

```java
Map<String, Object> resourceAccess = jwt.getClaimAsMap("resource_access");
if (resourceAccess != null && resourceAccess.get("my-api") instanceof Map<?, ?> client
        && client.get("roles") instanceof Collection<?> clientRoles) {
    // ... map clientRoles the same way
}
```

Client roles only appear in the token when that client is in the token's audience. If
`resource_access` has no `my-api` key at all, that is a Keycloak mapper/audience problem, not a
converter bug — check the decoded token before touching this code.

---

## Step 4: Use the roles

```java
import jakarta.annotation.security.RolesAllowed;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.oauth2.jwt.Jwt;

@RestController
@RequestMapping("/api")
class ReportController {

    @GetMapping("/reports")
    @PreAuthorize("hasRole('reader')")
    List<Report> list() { ... }

    @DeleteMapping("/reports/{id}")
    @PreAuthorize("hasAnyRole('admin', 'editor')")
    void delete(@PathVariable String id) { ... }

    @GetMapping("/me")
    Map<String, Object> me(@AuthenticationPrincipal Jwt jwt) {
        return Map.of(
            "sub", jwt.getSubject(),
            "username", jwt.getClaimAsString("preferred_username")
        );
    }
}
```

`hasRole('admin')` matches authority `ROLE_admin`. `hasAuthority('ROLE_admin')` matches the same
thing. `hasAuthority('admin')` matches nothing once your converter adds the prefix — pick one style
and hold it.

---

## Verify

**1. The context starts.** If discovery fails you get an exception at startup naming the issuer URI,
before any request arrives. That is the fastest signal that `issuer-uri` is wrong.

**2. No token is rejected:**

```bash
curl -i http://localhost:8080/api/reports
# expect: HTTP/1.1 401
# expect header: WWW-Authenticate: Bearer
```

**3. A real token is accepted.** Get one, then call:

```bash
TOKEN=$(curl -s -d 'client_id=my-api' -d 'client_secret=…' -d 'grant_type=client_credentials' \
  https://auth.example.com/realms/acme/protocol/openid-connect/token | jq -r .access_token)

curl -i -H "Authorization: Bearer $TOKEN" http://localhost:8080/api/reports
```

**4. Confirm the authorities are what you think.** This is the check that catches the `SCOPE_` bug,
and it is worth doing once explicitly rather than inferring it from a 403:

```java
@GetMapping("/whoami")
Map<String, Object> whoami(Authentication auth) {
    return Map.of("name", auth.getName(), "authorities", auth.getAuthorities().toString());
}
```

You want `[ROLE_admin, ROLE_user]`. If you see `[SCOPE_profile, SCOPE_email]`, the converter is not
wired. If you see `[]`, the converter is wired but found nothing — decode the token and look at
`realm_access`.

**5. Decode the token independently** and compare against what the API claims to see:

```bash
echo "$TOKEN" | cut -d. -f2 | base64 -d 2>/dev/null | jq '{iss, aud, azp, realm_access, resource_access}'
```

If `realm_access.roles` is missing from the token itself, stop editing Java — it is a role-mapper
problem in the realm, which is the `keycloak` skill's territory.

**6. Turn on the log that tells you why**, temporarily:

```yaml
logging:
  level:
    org.springframework.security: DEBUG
    org.springframework.security.oauth2.server.resource: TRACE
```

`TRACE` on `...oauth2.server.resource` is what prints the SpEL expression and the authorities it
found, for Option B. Take it back out before production — it logs claim contents.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| **401, `WWW-Authenticate: Bearer` with no `error`** | no token sent, or not `Bearer <token>` | check the client is actually setting the header |
| **401, `invalid_token`, "An error occurred while attempting to decode the Jwt: Signed JWT rejected: Another algorithm expected, or no matching key(s) found"** | `kid` not in the cached JWKS, or the token is from a different realm | confirm `iss` in the token equals `issuer-uri` exactly; restart to refetch keys |
| **401, "The iss claim is not valid"** | issuer mismatch — usually Keycloak behind a proxy issuing its internal hostname | fix Keycloak's hostname config, not the API; see [pattern-token-validation.md](pattern-token-validation.md) |
| **401, "The aud claim is not valid"** | `audiences` is set but no audience mapper exists on the client | add the audience mapper in Keycloak first, or drop the property until you do |
| **401, "Jwt expired at …"** | genuinely expired, or host clock drift | check NTP before widening skew |
| **403 on a token that authenticates fine** | **the default converter read `scope`** | Step 3 — this is the headline bug |
| **`/whoami` shows `SCOPE_profile`, `SCOPE_email`** | converter not wired into `oauth2ResourceServer` | confirm `.jwt(jwt -> jwt.jwtAuthenticationConverter(converter))` is present |
| **`/whoami` shows `[]`** | converter wired, claim missing or expression wrong | decode the token; check `realm_access.roles` exists; on Option B check for a typo — it fails silently |
| **`hasRole("admin")` denies but `hasAuthority("admin")` allows** | the `ROLE_` prefix is missing | add `"ROLE_" +` in the converter, or set `authority-prefix: ROLE_` |
| **`@PreAuthorize` never denies anything** | `@EnableMethodSecurity` absent | add it to the config class |
| **Every `POST`/`PUT` returns 403, `GET` works** | CSRF still enabled | `.csrf(csrf -> csrf.disable())` on this stateless chain |
| **App fails to start, `Unable to resolve the Configuration with the provided Issuer of …`** | Keycloak unreachable at startup, or `issuer-uri` has a trailing slash / wrong realm | curl `{issuer-uri}/.well-known/openid-configuration` from the API host |
| **`Cannot resolve org.springframework.boot:spring-boot-starter-security-oauth2-resource-server`** | that name does not exist before Boot 4.0 | use `spring-boot-starter-oauth2-resource-server` on 3.x |
| **`Could not find artifact org.keycloak:keycloak-spring-boot-starter`** | removed in Keycloak 25.0.0 | delete it; this file is the replacement |
| **`WebSecurityConfigurerAdapter cannot be resolved`** | removed in Spring Security 6.0 | rewrite as a `SecurityFilterChain` bean |
| **YAML parse error on `authorities-claim-expressions`** | unquoted value starting with `[` is a YAML flow sequence | quote it: `- "['realm_access']['roles']"` |
| **`MutuallyExclusiveConfigurationPropertiesException` at startup** | `authorities-claim-expressions` set together with `authorities-claim-name` or `-delimiter` | keep only the expressions |
| **`authorities-claim-expressions` appears to do nothing** | you are on Boot 3.x, where the property does not exist | use Option A |
