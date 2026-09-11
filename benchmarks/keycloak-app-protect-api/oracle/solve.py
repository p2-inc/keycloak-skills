#!/usr/bin/env python3
# Copyright 2026 Phase Two, Inc.
# SPDX-License-Identifier: Apache-2.0
"""Oracle for keycloak-app-protect-api.

Protects the Spring Boot inventory API with bearer-JWT validation against the
`acme` realm, exactly as the securing-apps skill's framework-springboot-api.md
reference prescribes (Option A: converter bean + SecurityFilterChain):

  1. spring.security.oauth2.resourceserver.jwt.issuer-uri -> the acme realm.
     No `audiences` property: the fixture realm deliberately ships no audience
     mapper on inventory-cli, and setting the property without the mapper
     rejects every token (see the reference's Audience section).
  2. KeycloakRealmRoleConverter - maps realm_access.roles to ROLE_* authorities;
     the default converter reads `scope` and would leave hasRole() denying
     every good token.
  3. SecurityFilterChain - /healthz public, /api/admin/** gated on the
     inventory-admin realm role, everything else authenticated; stateless,
     CSRF off (bearer-only chain).

Touches only /app/api. Performs zero Keycloak admin writes.
"""

import pathlib
import subprocess
import sys

API = pathlib.Path("/app/api")
SEC = API / "src/main/java/com/acme/inventory/security"

ISSUER = "http://localhost:8080/auth/realms/acme"

CONVERTER = """\
// Copyright 2026 Phase Two, Inc.
// SPDX-License-Identifier: Apache-2.0
package com.acme.inventory.security;

import java.util.Collection;
import java.util.List;
import java.util.Map;

import org.springframework.core.convert.converter.Converter;
import org.springframework.security.core.GrantedAuthority;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.oauth2.jwt.Jwt;

/**
 * Maps Keycloak's realm_access.roles into ROLE_-prefixed Spring authorities.
 * The default JwtGrantedAuthoritiesConverter reads the `scope` claim and
 * never sees Keycloak roles at all.
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
"""

SECURITY_CONFIG = """\
// Copyright 2026 Phase Two, Inc.
// SPDX-License-Identifier: Apache-2.0
package com.acme.inventory.security;

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
public class SecurityConfig {

    @Bean
    JwtAuthenticationConverter jwtAuthenticationConverter() {
        JwtAuthenticationConverter converter = new JwtAuthenticationConverter();
        converter.setJwtGrantedAuthoritiesConverter(new KeycloakRealmRoleConverter());
        // Display/logging only - preferred_username is mutable, so authorization
        // and ownership checks must key on sub.
        converter.setPrincipalClaimName("preferred_username");
        return converter;
    }

    @Bean
    SecurityFilterChain apiFilterChain(HttpSecurity http, JwtAuthenticationConverter converter) throws Exception {
        http
            .authorizeHttpRequests(auth -> auth
                .requestMatchers("/healthz").permitAll()
                .requestMatchers("/api/admin/**").hasRole("inventory-admin")
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
"""


def main() -> int:
    (SEC / "KeycloakRealmRoleConverter.java").write_text(CONVERTER)
    (SEC / "SecurityConfig.java").write_text(SECURITY_CONFIG)

    props = API / "src/main/resources/application.properties"
    text = props.read_text()
    if "issuer-uri" not in text:
        if not text.endswith("\n"):
            text += "\n"
        text += (
            "spring.security.oauth2.resourceserver.jwt.issuer-uri=" + ISSUER + "\n"
        )
        props.write_text(text)

    print("oracle: building offline to prove the solution compiles ...", flush=True)
    build = subprocess.run(
        ["mvn", "-o", "-q", "-DskipTests", "package"],
        cwd=API,
        capture_output=True,
        text=True,
    )
    sys.stdout.write(build.stdout)
    sys.stderr.write(build.stderr)
    if build.returncode != 0:
        print("oracle: offline build FAILED", flush=True)
        return 1

    print("oracle: done - issuer wired, realm-role converter installed, routes gated", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
