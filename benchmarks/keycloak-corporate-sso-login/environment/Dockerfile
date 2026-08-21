# The real Keycloak MCP server (Quarkus), pulled pre-built from Phase Two's own
# ECR staging registry rather than vendored in git. Tracks :latest deliberately, so
# benchmarks exercise the current staging build; that means a run is reproducible
# only relative to whatever :latest pointed at. Pin a digest here when a result has
# to be reproducible later. Requires ECR auth to pull - see docs/adding-a-skill.md. Requires `docker login quay.io`
# with Phase Two Quay credentials before building.
FROM 773532640636.dkr.ecr.us-west-2.amazonaws.com/mcp/staging:latest AS mcp-app

# Pinned to bookworm: trixie (the current python:3.12-slim) has no openjdk-17.
FROM python:3.12-slim-bookworm
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update -qq && apt-get install -y -qq \
    curl jq ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Java 21 for both Keycloak (26.x supports 17 and 21) and the MCP server jar
# (requires 21). One JVM install, not two. Bookworm's apt has no openjdk-21
# package, so this is a Temurin tarball - same pattern as the Keycloak install
# below. TARGETARCH is set automatically by buildx; map it to Adoptium's names.
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

# The real Keycloak MCP server (Quarkus), pulled from the mcp-app build stage
# above rather than vendored. Present in BOTH the with-skill and no-skill arms:
# it is environment, not skill, so the comparison measures skill effect on top
# of identical tool access, not tool access itself.
COPY --from=mcp-app /deployments /opt/mcp-app

WORKDIR /app

# bench's verifier hardening forces --rootdir=/app; pre-create it so pytest doesn't error.
# bench's skill-injection symlinks land in /home/agent/.claude/ etc.; pre-create with permissive
# ownership so the sandbox `agent` user can write session-env there.
RUN mkdir -p /app /home/agent/.claude /home/agent/.codex /home/agent/.opencode /home/agent/.agents \
    /logs/verifier /logs/agent /logs/artifacts && \
    chmod -R 777 /home/agent

# Two realms, imported on first start. Frozen fixtures.
#   acme        - the realm under configuration: a browser client and one internal
#                 staff account with a password. No identity provider.
#   contoso-idp - stands in for the customer's own identity provider, which they
#                 operate. Holds the federation client and the customer's staff.
COPY acme-realm.json /opt/keycloak/data/import/acme-realm.json
COPY contoso-idp-realm.json /opt/keycloak/data/import/contoso-idp-realm.json

# Admin credentials, and the federation details the customer's IT team handed over.
COPY admin_credentials.txt /root/admin_credentials.txt
COPY corporate_idp_details.txt /root/corporate_idp_details.txt

ENV KC_BOOTSTRAP_ADMIN_USERNAME=admin
ENV KC_BOOTSTRAP_ADMIN_PASSWORD=admin_change_me
ENV KC_HOSTNAME=http://localhost:8080/auth
ENV KC_HOSTNAME_BACKCHANNEL_DYNAMIC=false

# The MCP server, in-container, pointed at the co-located Keycloak. Bearer
# tokens the agent presents are forwarded verbatim to KEYCLOAK_URL - see
# mcp-bearer-token.txt for why the token itself has to be a fixed artifact
# rather than minted at boot.
ENV KEYCLOAK_URL=http://localhost:8080/auth
ENV OIDC_AUTH_SERVER_URL=http://localhost:8080/auth/realms/acme
ENV OIDC_DISCOVERY_ENABLED=false
ENV OIDC_JWKS_PATH=http://localhost:8080/auth/realms/acme/protocol/openid-connect/certs
ENV OIDC_TOKEN_ISSUER=http://localhost:8080/auth/realms/acme
ENV PORT=8090

# Starts Keycloak in the background. Readiness is a separate, idempotent gate any
# consumer can block on.
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
COPY wait_for_services.sh /usr/local/bin/wait-for-services
RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/wait-for-services

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["/bin/bash"]

# DO NOT bake skills here. `bench eval run --skill-mode with-skill --skills-dir <skills-dir>` injects
# them at deploy time. Baking them in makes the without-skills run a no-op.
