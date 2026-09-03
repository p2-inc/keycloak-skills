# Copyright 2026 Phase Two, Inc.
# SPDX-License-Identifier: Apache-2.0

# Stock upstream Keycloak only - this task's scored surface is app-side bearer-JWT
# validation, the realm fixture ships fully provisioned, and the correct solution
# performs zero Keycloak admin writes. No MCP server stage, no p2-inc extension jar
# (see task.md's sandbox comment for the reasoning).
FROM python:3.12-slim-bookworm
ENV DEBIAN_FRONTEND=noninteractive

# maven from apt (3.8.x on bookworm) drives the Spring Boot build; procps supplies
# pkill for the verifier's stop-the-old-jar step.
RUN apt-get update -qq && apt-get install -y -qq \
    curl jq ca-certificates maven procps \
    && rm -rf /var/lib/apt/lists/*

# Temurin JDK 21 - a full JDK, not a JRE: maven needs javac. Serves both Keycloak
# and the Spring Boot app.
ARG TARGETARCH
RUN case "${TARGETARCH}" in \
      arm64) T21_ARCH=aarch64 ;; \
      amd64) T21_ARCH=x64 ;; \
      *) echo "unsupported arch: ${TARGETARCH}" >&2; exit 1 ;; \
    esac && \
    curl -fsSL "https://api.adoptium.net/v3/binary/latest/21/ga/linux/${T21_ARCH}/jdk/hotspot/normal/eclipse" \
      -o /tmp/temurin21.tar.gz && \
    mkdir -p /opt/java21 && \
    tar -xzf /tmp/temurin21.tar.gz -C /opt/java21 --strip-components=1 && \
    rm /tmp/temurin21.tar.gz
ENV JAVA_HOME=/opt/java21
ENV PATH="${JAVA_HOME}/bin:${PATH}"
# The verifier and the sandbox agent user run under shells that do not inherit this
# ENV; give java/mvn stable homes on the default PATH.
RUN ln -sf /opt/java21/bin/java /usr/local/bin/java && \
    ln -sf /opt/java21/bin/javac /usr/local/bin/javac

ENV KEYCLOAK_VERSION=26.0.7
RUN curl -fsSL "https://github.com/keycloak/keycloak/releases/download/${KEYCLOAK_VERSION}/keycloak-${KEYCLOAK_VERSION}.tar.gz" -o /tmp/keycloak.tar.gz && \
    tar -xzf /tmp/keycloak.tar.gz -C /opt && \
    mv "/opt/keycloak-${KEYCLOAK_VERSION}" /opt/keycloak && \
    rm /tmp/keycloak.tar.gz

# pytest is baked in because the sandbox runs with no network at verify time.
RUN pip install --no-cache-dir requests==2.32.3 \
    pytest==8.4.1 pytest-json-ctrf==0.3.5

WORKDIR /app

# bench's verifier hardening forces --rootdir=/app; pre-create it so pytest doesn't error.
# bench's skill-injection symlinks land in /home/agent/.claude/ etc.; pre-create with
# permissive ownership so the sandbox `agent` user can write session-env there.
RUN mkdir -p /app /home/agent/.claude /home/agent/.codex /home/agent/.opencode /home/agent/.agents \
    /logs/verifier /logs/agent /logs/artifacts && \
    chmod -R 777 /home/agent /logs

# Admin credentials for the co-located Keycloak.
COPY admin_credentials.txt /root/admin_credentials.txt

# The Spring Boot app the agent protects. The local Maven repository is populated HERE,
# at build time, because the sandbox runs the agent with no network: `mvn` cannot
# download anything. Building the fixture once (package, then discard target/) caches
# every dependency and plugin the task needs - including spring-boot-starter-oauth2-
# resource-server, which is already declared in the fixture's pom.xml precisely so its
# jars are on disk for the agent to wire up. The repo lives at a shared, world-writable
# path (NOT /root/.m2) because the agent runs as a different user than this build; a
# global settings.xml points every user's mvn at it.
COPY api/ /app/api/
RUN mkdir -p /opt/m2repo && \
    printf '<settings xmlns="http://maven.apache.org/SETTINGS/1.0.0">\n  <localRepository>/opt/m2repo</localRepository>\n</settings>\n' \
      > /usr/share/maven/conf/settings.xml && \
    cd /app/api && \
    mvn -q -DskipTests package && \
    rm -rf target && \
    chmod -R 777 /opt/m2repo /app/api

# Two realms, imported on first start - placed after the Maven build so editing a
# realm fixture doesn't invalidate (and re-run) the app build layer. `acme` is the
# realm the API must trust: realm role inventory-admin, users alice (has it) / bob
# (does not), and the public inventory-cli client with direct-access grants so
# tokens are mintable in-container. `acme-evil` is the foreign-token fixture: the
# SAME usernames, passwords, role, client id AND signing key as acme - only its
# issuer differs. Sharing the key is deliberate and load-bearing: it is what makes
# `jwk-set-uri` (signature-only, no issuer check) a detectable wrong answer where a
# per-realm key would let the signature check mask the missing issuer validation.
COPY acme-realm.json /opt/keycloak/data/import/acme-realm.json
COPY acme-evil-realm.json /opt/keycloak/data/import/acme-evil-realm.json

ENV KC_BOOTSTRAP_ADMIN_USERNAME=admin
ENV KC_BOOTSTRAP_ADMIN_PASSWORD=admin_change_me
ENV KC_HOSTNAME=http://localhost:8080/auth
ENV KC_HOSTNAME_BACKCHANNEL_DYNAMIC=false

# Starts Keycloak in the background, then hands straight over to the container's
# command. Readiness is a separate, idempotent gate any consumer can block on.
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
COPY wait_for_services.sh /usr/local/bin/wait-for-services
RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/wait-for-services

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["/bin/bash"]

# DO NOT bake skills here. `bench eval run --skill-mode with-skill --skills-dir <skills-dir>`
# injects them at deploy time. Baking them in makes the without-skills run a no-op.
