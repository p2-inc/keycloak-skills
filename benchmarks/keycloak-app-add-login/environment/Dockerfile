# The real Keycloak MCP server (Quarkus), pulled pre-built from Phase Two's own ECR
# staging registry rather than vendored in git. Requires ECR auth to pull - see
# docs/adding-a-skill.md.
#
# PINNED BY DIGEST, deliberately, unlike the other tasks in this repo which track
# :latest. This task needs `updateOidcClient` (it repairs an existing client rather
# than creating one), and that tool only landed in the source on 2026-08-25, commit
# 594b8f2. A locally cached :latest from 2026-08-24 silently lacked it - the tool
# call would simply not exist, and the MCP arm would look like a skill failure when
# it was a stale image. Tracking a moving tag cannot express "new enough".
#
# This digest is image tag bad4a9c0f, pushed 2026-08-26, built from commit bad4a9c,
# verified to contain updateOidcClient and rotateClientSecret. ECR image tags in this
# registry are git short SHAs, so an image's contents can be checked against the
# phasetwo-mcp history without pulling it.
#
# Bump this when the task needs a newer tool; don't silently move it to :latest.
FROM 773532640636.dkr.ecr.us-west-2.amazonaws.com/mcp/staging@sha256:1bf446f6865d76a6b3075e1506d635cde2ad13c414ea12d5244a3a424497cf6d AS mcp-app

# Stock upstream Keycloak is enough here: this task's whole surface - updating an
# existing OIDC client's redirect URIs and web origins, and a browser auth-code
# login - is plain Keycloak functionality plus the phasetwo-mcp server that drives
# it. No provider jar to bake in.
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


# Node 22 for the Vite/React app the agent edits. Temurin-style tarball install,
# same pattern as the Java one above.
ARG TARGETARCH
RUN case "${TARGETARCH}" in \
      arm64) NODE_ARCH=arm64 ;; \
      amd64) NODE_ARCH=x64 ;; \
      *) echo "unsupported arch: ${TARGETARCH}" >&2; exit 1 ;; \
    esac && \
    NODE_VERSION=22.14.0 && \
    curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${NODE_ARCH}.tar.gz" \
      -o /tmp/node.tar.gz && \
    mkdir -p /opt/node && \
    tar -xzf /tmp/node.tar.gz -C /opt/node --strip-components=1 && \
    rm /tmp/node.tar.gz
ENV PATH="/opt/node/bin:${PATH}"
# Symlink into the default PATH as well. The verifier runs under a shell that does
# not inherit this ENV, and npm's shim is `#!/usr/bin/env node` - without this it
# fails with "env: node: No such file or directory" even when npm itself is found.
RUN ln -sf /opt/node/bin/node /usr/local/bin/node && \
    ln -sf /opt/node/bin/npm /usr/local/bin/npm && \
    ln -sf /opt/node/bin/npx /usr/local/bin/npx

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

# The realm the agent configures, imported on first start. Frozen fixture: the
# acme-portal public browser client, deliberately stale - its redirect URI points at
# an old callback and it has NO web origins - plus an acme-department protocol mapper
# that must survive whatever the agent does, and the portal-user login. Includes the
# same fixed RSA signing key and mcp-operator user as the other MCP-wired tasks in
# this repo, for the MCP server's crafted token validation.
COPY acme-realm.json /opt/keycloak/data/import/acme-realm.json

# Admin credentials for the co-located Keycloak.
COPY admin_credentials.txt /root/admin_credentials.txt

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


# The React skeleton the agent wires login into. node_modules is installed HERE,
# at build time, because the sandbox runs the agent with no network: `npm install`
# is not available to it. Everything the task needs - oidc-spa, zod, react, vite -
# must therefore already be on disk. `npm ci` needs a lockfile, so generate one in
# the same layer and keep it: the install must be reproducible, and the agent may
# legitimately read it to see what is available.
COPY frontend/package.json /app/frontend/package.json
RUN cd /app/frontend && npm install --no-audit --no-fund && npm cache clean --force
COPY frontend/ /app/frontend/
RUN chmod -R 777 /app/frontend

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
