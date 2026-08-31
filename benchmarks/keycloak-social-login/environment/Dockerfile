# Copyright 2026 Phase Two, Inc.
# SPDX-License-Identifier: Apache-2.0

# The real Keycloak MCP server (Quarkus), pulled pre-built from Phase Two's own
# ECR staging registry rather than vendored in git. Tracks :latest deliberately, so
# benchmarks exercise the current staging build; that means a run is reproducible
# only relative to whatever :latest pointed at. Pin a digest here when a result has
# to be reproducible later. Requires ECR auth to pull - see docs/adding-a-skill.md. Same digest as the other MCP-wired
# tasks in this repo (keycloak-magic-link-login, keycloak-idp-org-restrict-login).
FROM 773532640636.dkr.ecr.us-west-2.amazonaws.com/mcp/staging:latest AS mcp-app

# Stock upstream Keycloak is enough here - unlike keycloak-idp-org-restrict-login
# (which needs the real p2-inc keycloak-orgs extension for ext-select-org) or
# keycloak-magic-link-login (which needs the p2-inc keycloak-magic-link provider),
# this task's whole surface - createSocialIdp, generic identity-provider REST
# endpoints, IdP attribute mappers - is plain Keycloak functionality plus the
# phasetwo-mcp server that drives it. No provider jar to bake in.
FROM python:3.12-slim-bookworm
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update -qq && apt-get install -y -qq \
    curl jq ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Java 21 for the Keycloak MCP server (Quarkus) - Bookworm's apt only has 17,
# so this is a Temurin tarball, same pattern as the other tasks' Dockerfiles.
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
RUN pip install --no-cache-dir requests==2.32.3 \
    pytest==8.4.1 pytest-json-ctrf==0.3.5

WORKDIR /app

# bench's verifier hardening forces --rootdir=/app; pre-create it so pytest doesn't error.
# bench's skill-injection symlinks land in /home/agent/.claude/ etc.; pre-create with permissive
# ownership so the sandbox `agent` user can write session-env there.
RUN mkdir -p /app /home/agent/.claude /home/agent/.codex /home/agent/.opencode /home/agent/.agents \
    /logs/verifier /logs/agent /logs/artifacts && \
    chmod -R 777 /home/agent /logs

# The realm the agent configures, imported on first start. Frozen fixture: a public
# browser client and no identity provider - the agent creates one. Includes the same
# fixed RSA signing key and mcp-operator user as the other MCP-wired tasks in this
# repo, for the MCP server's crafted token validation.
COPY acme-realm.json /opt/keycloak/data/import/acme-realm.json

# Admin credentials, and the GitHub OAuth App details Acme's engineering team
# handed over (fixture client ID/secret, not real GitHub-issued values).
COPY admin_credentials.txt /root/admin_credentials.txt
COPY github_oauth_app_details.txt /root/github_oauth_app_details.txt

# The real Keycloak MCP server (Quarkus), pulled from the mcp-app build stage
# above rather than vendored - avoids needing Maven + the full dependency tree
# at image-build time. Present in BOTH the with-skill and no-skill arms: it is
# environment, not skill, so the comparison measures skill effect on top of
# identical tool access, not tool access itself.
COPY --from=mcp-app /deployments /opt/mcp-app

# The deployment-token proxy this task needs, same as the other MCP-wired tasks:
# IdentityProviderTools' tools (createSocialIdp, addIdpAttributeMapper, ...) are
# written for Phase Two's real product shape - a control-plane realm plus a
# *separate*, remotely-hosted "deployment" those tools operate on. This sandbox
# has no such backend, so the proxy answers the one deployment-token exchange
# itself and forwards everything else straight through to the co-located Keycloak.
RUN mkdir -p /opt/mcp
COPY deployment_token_proxy.py /opt/mcp/deployment_token_proxy.py
RUN chmod +x /opt/mcp/deployment_token_proxy.py

ENV KC_BOOTSTRAP_ADMIN_USERNAME=admin
ENV KC_BOOTSTRAP_ADMIN_PASSWORD=admin_change_me
ENV KC_HOSTNAME=http://localhost:8080/auth
ENV KC_HOSTNAME_BACKCHANNEL_DYNAMIC=false

# The MCP server, in-container, pointed at the proxy rather than Keycloak
# directly - KEYCLOAK_URL is the only route its admin client has to any
# Keycloak, so this is what makes the synthetic deployment-token exchange
# reachable. Bearer tokens the agent presents are validated against the
# co-located Keycloak's real JWKS - same fixed-key fixture as the other
# MCP-wired tasks in this repo.
ENV KEYCLOAK_URL=http://localhost:8091/auth
ENV OIDC_AUTH_SERVER_URL=http://localhost:8080/auth/realms/acme
ENV OIDC_DISCOVERY_ENABLED=false
ENV OIDC_JWKS_PATH=http://localhost:8080/auth/realms/acme/protocol/openid-connect/certs
ENV OIDC_TOKEN_ISSUER=http://localhost:8080/auth/realms/acme
ENV PORT=8090

# Starts Keycloak, the deployment-token proxy, and the MCP server in the
# background, then hands straight over to the container's command. Readiness
# is a separate, idempotent gate any consumer can block on.
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
COPY wait_for_services.sh /usr/local/bin/wait-for-services
RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/wait-for-services

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["/bin/bash"]

# DO NOT bake skills here. `bench eval run --skill-mode with-skill --skills-dir <skills-dir>` injects
# them at deploy time. Baking them in makes the without-skills run a no-op.
