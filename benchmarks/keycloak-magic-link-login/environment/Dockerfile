# The real Keycloak MCP server (Quarkus), pulled pre-built from Phase Two's own
# registry rather than vendored in git - pinned by digest, not :latest, so this
# stays reproducible even if the tag moves.
FROM quay.io/phasetwo/phasetwo-mcp@sha256:81dac19771962fd92b72c6b22c236db6070c0b024a5b2dc0bd514eb3a173d537 AS mcp-app

# Pinned to bookworm: trixie (the current python:3.12-slim) has no openjdk-17.
FROM python:3.12-slim-bookworm
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update -qq && apt-get install -y -qq \
    curl jq ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Java 21, not the apt-available 17: the keycloak-magic-link provider crashes
# Keycloak's build step under 17 (a Quarkus classloading NPE surfaces while
# formatting an unrelated log message, masking whatever the real complaint
# is), and is clean under 21. Bookworm's apt has no openjdk-21 package, so
# this is a Temurin tarball - same pattern as the Keycloak install below.
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

# The real, open-source keycloak-magic-link provider (p2-inc, Elastic License 2.0),
# pre-built on the host and dropped straight into Keycloak's providers directory -
# same pre-built-artifact pattern as the Keycloak MCP server jar in the
# corporate-sso-login task. It registers its own authenticator, action-token
# handler, and email templates; Keycloak auto-detects it and auto-creates a
# built-in "magic link" flow on every realm without any custom flow authoring.
COPY keycloak-magic-link.jar /opt/keycloak/providers/keycloak-magic-link.jar

# pytest is baked in because the sandbox runs with no network at verify time.
# aiosmtpd backs the local outgoing-mail capture server.
RUN pip install --no-cache-dir requests==2.32.3 aiosmtpd==1.4.6 \
    pytest==8.4.1 pytest-json-ctrf==0.3.5

WORKDIR /app

# bench's verifier hardening forces --rootdir=/app; pre-create it so pytest doesn't error.
# bench's skill-injection symlinks land in /home/agent/.claude/ etc.; pre-create with permissive
# ownership so the sandbox `agent` user can write session-env there.
RUN mkdir -p /app /home/agent/.claude /home/agent/.codex /home/agent/.opencode /home/agent/.agents \
    /logs/verifier /logs/agent /logs/artifacts /var/mail-capture && \
    chmod -R 777 /home/agent /var/mail-capture

# The realm the agent configures, imported on first start. Frozen fixture: two
# staff accounts with passwords, a public browser client, and no outgoing-mail
# configuration - the built-in "magic link" flow exists (the provider creates it
# on every realm) but is neither configured for mail delivery nor bound. Includes
# fixed RSA signing key and mcp-operator user for MCP server's crafted token validation.
COPY acme-realm.json /opt/keycloak/data/import/acme-realm.json

# Admin credentials, and connection details for the local mail-capture server.
COPY admin_credentials.txt /root/admin_credentials.txt
COPY mail_server_details.txt /root/mail_server_details.txt

# The mail capture server itself - fixed infrastructure, not something to configure.
COPY mail_capture_server.py /opt/mail/mail_capture_server.py

# The real Keycloak MCP server (Quarkus), pulled from the mcp-app build stage
# above rather than vendored - avoids needing Maven + the full dependency tree
# at image-build time. Present in BOTH the with-skill and no-skill arms: it is
# environment, not skill, so the comparison measures skill effect on top of
# identical tool access, not tool access itself.
COPY --from=mcp-app /deployments /opt/mcp-app

# The deployment-token proxy this task alone needs: bindingAuthenticationFlow's
# tools (bindRealmAuthenticationFlow, listAuthenticationFlows, ...) are written
# for Phase Two's real product shape - a control-plane realm plus a *separate*,
# remotely-hosted "deployment" those tools operate on. This sandbox has no such
# backend, so the proxy answers the one deployment-token exchange itself and
# forwards everything else straight through to the co-located Keycloak.
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
# co-located Keycloak's real JWKS - see mcp-bearer-token.txt for why the
# token itself has to be a fixed artifact rather than minted at boot.
ENV KEYCLOAK_URL=http://localhost:8091/auth
ENV OIDC_AUTH_SERVER_URL=http://localhost:8080/auth/realms/acme
ENV OIDC_DISCOVERY_ENABLED=false
ENV OIDC_JWKS_PATH=http://localhost:8080/auth/realms/acme/protocol/openid-connect/certs
ENV OIDC_TOKEN_ISSUER=http://localhost:8080/auth/realms/acme
ENV PORT=8090

# Starts Keycloak and the mail capture server in the background. Readiness is a
# separate, idempotent gate any consumer can block on.
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
COPY wait_for_services.sh /usr/local/bin/wait-for-services
RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/wait-for-services

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["/bin/bash"]

# DO NOT bake skills here. `bench eval run --skill-mode with-skill --skills-dir <skills-dir>` injects
# them at deploy time. Baking them in makes the without-skills run a no-op.
