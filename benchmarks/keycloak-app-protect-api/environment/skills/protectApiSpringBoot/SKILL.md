---
name: protectApiSpringBoot
description: >-
  Protect a Spring Boot API with bearer JWTs issued by Keycloak: validate tokens against
  the realm's JWKS and map Keycloak realm roles to Spring Security authorities so
  hasRole(...) actually grants access. Use whenever someone wants to "secure my API",
  "validate a JWT", "require a token on my endpoints", "map Keycloak roles to
  authorities", or is debugging a 401/403 from a Spring Boot resource server. Bearer
  tokens only - no login UI, no redirect, no cookie session. Covers the issuer-uri
  configuration, the realm_access.roles converter the default setup is missing, the
  SecurityFilterChain shape (stateless, CSRF off, per-route rules), and the audience
  trap. One skill for one job; it does not cover browser login or native apps.
---

<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# Spring Boot — bearer-JWT resource server, with Keycloak roles mapped to Spring authorities

Wiring for a Spring Boot service that accepts `Authorization: Bearer <jwt>`, verifies the
token against your realm's JWKS, and converts Keycloak's roles into Spring Security
authorities so `hasRole(...)` and `@PreAuthorize` actually grant access.

## The dead adapter — recognise it, delete it

`org.keycloak:keycloak-spring-boot-starter` and `keycloak-spring-security-adapter` were
**removed in Keycloak 25.0.0**. `KeycloakWebSecurityConfigurerAdapter` does not compile
against Spring Security 6+. If the project (or your recollection) reaches for any of
those, stop: Spring Security's own resource-server support is the replacement, and it is
all Keycloak needs.

## Step 1: The dependency

On Spring Boot **3.x** the artifact is `spring-boot-starter-oauth2-resource-server`
(Boot 4.x renamed it to `spring-boot-starter-security-oauth2-resource-server`; that name
does not exist before 4.0). No `<version>` — the Boot parent supplies it. Check the
`pom.xml` first: the dependency may already be declared, and in a no-network sandbox the
one already cached is the one you use.

## Step 2: The configuration — two lines, one trap

```properties
spring.security.oauth2.resourceserver.jwt.issuer-uri=http://<keycloak-host>/auth/realms/<realm>
```

- `issuer-uri` is the realm issuer: scheme, host, port, path, realm name, **no trailing
  slash**. Boot fetches `{issuer-uri}/.well-known/openid-configuration` **at startup**
  and builds a caching JwtDecoder that validates signature AND `iss`.
- Do **not** use `jwk-set-uri` instead: it verifies the signature but never checks the
  issuer — a token from any realm sharing those keys is accepted.
- **The audience trap**: Keycloak does not put a useful `aud` in access tokens by
  default; that needs an audience mapper on the client (realm configuration). Setting
  `spring.security.oauth2.resourceserver.jwt.audiences` when no mapper exists rejects
  **every** token — valid ones included — with "The aud claim is not valid". If you
  cannot add the mapper, leave the property unset.

## Step 3: The role converter — the part the default setup is missing

Spring Security's default authorities converter reads the `scope`/`scp` claim and
prefixes `SCOPE_`. Keycloak puts roles in `realm_access.roles` (and
`resource_access.<client>.roles`) — which the default never touches. Out of the box,
against a perfectly valid Keycloak token: the token verifies, the user is authenticated,
and **every `hasRole(...)` check denies**. A 403 on a good token is this bug.

`hasRole("x")` matches the authority `ROLE_x` — the prefix is added by `hasRole`, so the
converter must emit `ROLE_`-prefixed authorities.

```java
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

`getClaimAsMap` returns `null` — not an empty map — for an absent claim; check it first.
Returning `List.of()` rather than throwing is deliberate: a user with no realm roles is a
legitimate authenticated user with zero authorities.

## Step 4: The filter chain

`SecurityFilterChain` bean style — `WebSecurityConfigurerAdapter` was removed in Spring
Security 6.0:

```java
@Configuration
@EnableWebSecurity
@EnableMethodSecurity
public class SecurityConfig {

    @Bean
    JwtAuthenticationConverter jwtAuthenticationConverter() {
        JwtAuthenticationConverter converter = new JwtAuthenticationConverter();
        converter.setJwtGrantedAuthoritiesConverter(new KeycloakRealmRoleConverter());
        converter.setPrincipalClaimName("preferred_username"); // display only; authorize on sub
        return converter;
    }

    @Bean
    SecurityFilterChain apiFilterChain(HttpSecurity http, JwtAuthenticationConverter converter) throws Exception {
        http
            .authorizeHttpRequests(auth -> auth
                .requestMatchers("/healthz").permitAll()          // keep probes public
                .requestMatchers("/api/admin/**").hasRole("some-realm-role")
                .anyRequest().authenticated()
            )
            .oauth2ResourceServer(oauth2 -> oauth2
                .jwt(jwt -> jwt.jwtAuthenticationConverter(converter))
            )
            .sessionManagement(s -> s.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
            .csrf(csrf -> csrf.disable());
        return http.build();
    }
}
```

Three things in that chain are load-bearing:

- **`SessionCreationPolicy.STATELESS`** — without it every request gets an `HttpSession`
  and a `JSESSIONID`; a bearer API must not carry session state.
- **`csrf.disable()`** — CSRF defends cookie-borne credentials; an `Authorization` header
  is not sent automatically by the browser, so there is nothing to forge. Disable it only
  because this chain is stateless and bearer-only.
- **`@EnableMethodSecurity`** — without it `@PreAuthorize` annotations are silently inert.

Declaring a `JwtAuthenticationConverter` bean makes Boot's property-driven converter back
off (`@ConditionalOnMissingBean`), so the bean always wins.

Keep route rules honest: protect what must be protected and **only** that. An endpoint
monitoring probes unauthenticated (a health check) must stay `permitAll` — locking it
breaks the monitoring contract, and "everything 401s" is not the same as "secure".

## Diagnosing the two failure shapes

| Symptom | Meaning | Fix |
|---|---|---|
| 401 with a valid-looking token | the token itself was rejected: wrong `issuer-uri`, expired, tampered, foreign realm, or the audiences property set without a mapper | check the `WWW-Authenticate` header detail; fix issuer/audience config |
| 403 on a good token, authenticated user | token verified, authorization denied: roles never mapped (default `SCOPE_` converter still active) or role name/prefix mismatch | install the realm-role converter; remember `hasRole("x")` ⇔ authority `ROLE_x` |
