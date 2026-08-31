# Copyright 2026 Phase Two, Inc.
# SPDX-License-Identifier: Apache-2.0

# The real Keycloak MCP server (Quarkus), pulled pre-built from Phase Two's own
# ECR staging registry rather than vendored in git. Tracks :latest deliberately, so
# benchmarks exercise the current staging build; that means a run is reproducible
# only relative to whatever :latest pointed at. Pin a digest here when a result has
# to be reproducible later. Requires ECR auth to pull - see docs/adding-a-skill.md.
FROM 773532640636.dkr.ecr.us-west-2.amazonaws.com/mcp/staging:latest AS mcp-app

# Pinned to bookworm for Playwright/Chromium apt dependency compatibility.
FROM python:3.12-slim-bookworm
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update -qq && apt-get install -y -qq \
    curl jq ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Java 21 for Keycloak itself (not for any custom provider this time - pure
# WebAuthn passwordless is a built-in Keycloak feature, no extra jar needed).
# TARGETARCH is set automatically by buildx; map it to Adoptium's names.
ARG TARGETARCH
RUN case "${TARGETARCH}" in \
      arm64) T21_ARCH=aarch64 ;; \
      amd64) T21_ARCH=x64 ;; \
      *) echo "unsupported arch: ${TARGETARCH}" >&2; exit 1 ;; \
    esac && \
    curl -fsSL "https://api.adoptium.net/v3/binary/latest/21/ga/linux/${T21_ARCH}/jre/hotspot/normal/eclipse" \
      -o /tmp/temurin21.tar.gz && \
    mkdir -p /opt/java21 && \
    tar -xzf /tmp/temurin21.tar.gz -C /opt/java21 --strip-components=1 && \
    rm /tmp/temurin21.tar.gz
ENV JAVA_HOME=/opt/java21
ENV PATH="${JAVA_HOME}/bin:${PATH}"

ENV KEYCLOAK_VERSION=26.0.7
RUN curl -fsSL "https://github.com/keycloak/keycloak/releases/download/${KEYCLOAK_VERSION}/keycloak-${KEYCLOAK_VERSION}.tar.gz" -o /tmp/keycloak.tar.gz && \
    tar -xzf /tmp/keycloak.tar.gz -C /opt && \
    mv "/opt/keycloak-${KEYCLOAK_VERSION}" /opt/keycloak && \
    rm /tmp/keycloak.tar.gz

# pytest is baked in because the sandbox runs with no network at verify time.
# aiosmtpd backs the local outgoing-mail capture server. playwright drives a
# real Chromium instance with a CDP virtual WebAuthn authenticator - both the
# oracle and the verifier need this to perform an actual passkey registration
# and login ceremony (the crypto exchange can't be faked with a curl call the
# way magic-link's plain redirect-following could).
RUN pip install --no-cache-dir requests==2.32.3 aiosmtpd==1.4.6 \
    pytest==8.4.1 pytest-json-ctrf==0.3.5 playwright==1.48.0 && \
    playwright install --with-deps chromium

WORKDIR /app

# bench's verifier hardening forces --rootdir=/app; pre-create it so pytest doesn't error.
# bench's skill-injection symlinks land in /home/agent/.claude/ etc.; pre-create with permissive
# ownership so the sandbox `agent` user can write session-env there.
RUN mkdir -p /app /home/agent/.claude /home/agent/.codex /home/agent/.opencode /home/agent/.agents \
    /logs/verifier /logs/agent /logs/artifacts /var/mail-capture && \
    chmod -R 777 /home/agent /var/mail-capture

# The realm the agent configures, imported on first start. Frozen fixture: two
# staff accounts with NO credentials and NO required actions set, a public
# browser client, and no outgoing-mail configuration. Includes the same fixed
# RSA signing key and mcp-operator user as the other MCP-wired tasks, for the
# MCP server's crafted token validation.
COPY acme-realm.json /opt/keycloak/data/import/acme-realm.json

# Admin credentials, and connection details for the local mail-capture server.
COPY admin_credentials.txt /root/admin_credentials.txt
COPY mail_server_details.txt /root/mail_server_details.txt

# The mail capture server itself - fixed infrastructure, not something to configure.
COPY mail_capture_server.py /opt/mail/mail_capture_server.py

# The real Keycloak MCP server (Quarkus), pulled from the mcp-app build stage
# above. Present in BOTH the with-skill and no-skill arms: it is environment,
# not skill.
COPY --from=mcp-app /deployments /opt/mcp-app

# The deployment-token proxy this task needs for the same reason as
# keycloak-magic-link-login: bindingAuthenticationFlow's tools assume a
# separate, remotely-hosted "deployment" that this sandbox doesn't have.
RUN mkdir -p /opt/mcp
COPY deployment_token_proxy.py /opt/mcp/deployment_token_proxy.py
RUN chmod +x /opt/mcp/deployment_token_proxy.py

ENV KC_BOOTSTRAP_ADMIN_USERNAME=admin
ENV KC_BOOTSTRAP_ADMIN_PASSWORD=admin_change_me
ENV KC_HOSTNAME=http://localhost:8080/auth
ENV KC_HOSTNAME_BACKCHANNEL_DYNAMIC=false

ENV KEYCLOAK_URL=http://localhost:8091/auth
ENV OIDC_AUTH_SERVER_URL=http://localhost:8080/auth/realms/acme
ENV OIDC_DISCOVERY_ENABLED=false
ENV OIDC_JWKS_PATH=http://localhost:8080/auth/realms/acme/protocol/openid-connect/certs
ENV OIDC_TOKEN_ISSUER=http://localhost:8080/auth/realms/acme
ENV PORT=8090

# Starts Keycloak, the mail capture server, the deployment-token proxy, and the
# MCP server in the background. Readiness is a separate, idempotent gate any
# consumer can block on.
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
COPY wait_for_services.sh /usr/local/bin/wait-for-services
RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/wait-for-services

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["/bin/bash"]

# DO NOT bake skills here. `bench eval run --skill-mode with-skill --skills-dir <skills-dir>` injects
# them at deploy time. Baking them in makes the without-skills run a no-op.
