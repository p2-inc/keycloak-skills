# Copyright 2026 Phase Two, Inc.
# SPDX-License-Identifier: Apache-2.0

# The real Keycloak MCP server (Quarkus), pulled pre-built from Phase Two's own
# registry - pinned by digest, not :latest, so this stays reproducible even if the
# tag moves. Requires `docker login quay.io` with Phase Two Quay credentials.
#
# NOTE: this digest predates two efficiency fixes in keycloak-MCP-server (commit
# 9d1788c): the MicroProfile default response exception mapper is still enabled, so
# 4xx bodies are replaced by an opaque "status code 400", and importAuthenticationFlow
# does not yet strip `ifResourceExists`. The task passes on this image, but an agent
# using the MCP tools burns ~2x the calls and ~5x the cost working around the opaque
# error. Re-pin to a newer digest once those fixes ship to quay.
FROM 773532640636.dkr.ecr.us-west-2.amazonaws.com/mcp/staging:latest AS mcp-app

# Phase Two's own Keycloak distribution - includes the REAL p2-inc keycloak-orgs
# extension (io.phasetwo.keycloak-keycloak-orgs jar, baked into providers/ already
# built), which is what actually provides the `ext-select-org` authenticator this
# task's bundled flow assets need. Unlike the other Keycloak-based tasks in this
# repo, plain upstream Keycloak is not enough here - there is no native-Keycloak
# equivalent for `ext-select-org`.
#
# Native Keycloak's own built-in Organizations feature is deliberately NOT used -
# Phase Two's product never enables it (see
# https://github.com/p2-inc/keycloak-orgs/blob/main/docs/note-keycloak-organizations-feature.md).
# No --features=organization flag is passed anywhere in this task.
FROM quay.io/phasetwo/phasetwo-keycloak@sha256:af0cb0d9fb3a73aa619678f5d290d5bd048908744996fe7ec435991ea0a93b03
USER root

# The p2-inc keycloak-atomic-auth-flows extension: authors custom authentication
# flows AND binds them in one atomic call, via
# POST /admin/realms/{realm}/authentication-flow/import.
#
# This is REQUIRED here, not a convenience. Keycloak's own partialImport endpoint
# has no handler for authentication flows at all (only clients, roles, identity
# providers, IdP mappers, groups and users - see PartialImportManager in Keycloak's
# source), so an authenticationFlows array sent to it is silently ignored: 200 OK,
# added: 0, no error. Without this extension the only route is the long manual
# sequence of create-flow / create-sub-flow / add-execution / set-requirement /
# attach-config calls.
COPY keycloak-atomic-auth-flows.jar /opt/keycloak/providers/keycloak-atomic-auth-flows.jar

# Wolfi (apk-based) - no python/curl/jq/bash in the base image.
#
# util-linux-bins matters for a non-obvious reason: bench launches the agent with
#   `if setpriv --help | grep -q reuid; then setpriv --reuid=agent ...; else su -l agent -c ...; fi`
# This base image's /usr/bin/setpriv is a busybox symlink WITHOUT --reuid support, so
# bench silently falls back to `su -l`, which is a LOGIN shell and therefore RESETS the
# environment - dropping ANTHROPIC_API_KEY and the provider base URL before the agent
# starts, which surfaces only as an opaque "ACP error -32000: Authentication required".
# util-linux-bins replaces that symlink with the real setpriv, which preserves the env.
RUN apk update && apk add --no-cache python3 py3-pip curl jq bash util-linux-bins

# pytest is baked in because the sandbox runs with no network at verify time.
RUN pip install --break-system-packages --no-cache-dir \
    requests==2.32.3 pytest==8.4.1 pytest-json-ctrf==0.3.5

WORKDIR /app

# bench runs the agent as an unprivileged `agent` user and chowns its home to
# agent:agent. Unlike the Debian-based images the other tasks in this repo use,
# this Wolfi base has no such user (only `keycloak`), so that chown fails and the
# whole run errors out before the agent starts - create it explicitly.
RUN adduser -D -h /home/agent agent 2>/dev/null || true

# bench's verifier hardening forces --rootdir=/app; pre-create it so pytest doesn't error.
# bench's skill-injection symlinks land in /home/agent/.claude/ etc.; pre-create with permissive
# ownership so the sandbox `agent` user can write session-env there.
RUN mkdir -p /app /home/agent/.claude /home/agent/.codex /home/agent/.opencode /home/agent/.agents \
    /logs/verifier /logs/agent /logs/artifacts && \
    chown -R agent:agent /home/agent && \
    chmod -R 777 /home/agent /logs

# The realm the agent configures, imported on first start. Frozen fixture: a public
# browser client, no organizations, and no identity provider - the agent creates all
# of those. Includes the same fixed RSA signing key and mcp-operator user as the other
# MCP-wired tasks, for the MCP server's crafted token validation.
COPY acme-realm.json /opt/keycloak/data/import/acme-realm.json
# Stands in for the customer's own identity provider, which they operate.
COPY partner-idp-realm.json /opt/keycloak/data/import/partner-idp-realm.json

# Admin credentials.
COPY admin_credentials.txt /root/admin_credentials.txt
# The federation details the partner's IT team handed over.
COPY partner_idp_details.txt /root/partner_idp_details.txt

# The real Keycloak MCP server (Quarkus), pulled from the mcp-app build stage
# above. Present in BOTH the with-skill and no-skill arms: it is environment,
# not skill, so the comparison measures skill effect on top of identical tool
# access, not tool access itself.
COPY --from=mcp-app /deployments /opt/mcp-app

# The deployment-token proxy, same as the magic-link and passkey tasks need:
# AuthenticationFlowTools' tools (importAuthenticationFlow, listAuthenticationFlows,
# bindRealmAuthenticationFlow, ...) are written for Phase Two's real product shape -
# a control-plane realm plus a *separate*, remotely-hosted "deployment" they operate
# on, reached by exchanging a deploymentId at
# POST /realms/{realm}/deployments/{deploymentId}/token. This sandbox has no such
# backend, so without the proxy every one of those tools fails with a 404 on that
# exchange. The proxy answers that single path itself ("the deployment is right
# here") and forwards everything else untouched to the co-located Keycloak.
RUN mkdir -p /opt/mcp
COPY deployment_token_proxy.py /opt/mcp/deployment_token_proxy.py
RUN chmod +x /opt/mcp/deployment_token_proxy.py

ENV KC_BOOTSTRAP_ADMIN_USERNAME=admin
ENV KC_BOOTSTRAP_ADMIN_PASSWORD=admin_change_me
ENV KC_HOSTNAME=http://localhost:8080/auth
ENV KC_HOSTNAME_BACKCHANNEL_DYNAMIC=false
ENV KC_HTTP_ENABLED=true

# The MCP server, in-container, pointed at the co-located Keycloak directly.
# Bearer tokens the agent presents are validated against Keycloak's real JWKS -
# same fixed-key fixture as the other MCP-wired tasks.
# Points at the deployment-token proxy (:8091), not Keycloak (:8080), directly -
# KEYCLOAK_URL is the MCP server's only route to any Keycloak, so this is what makes
# the synthetic deployment-token exchange reachable. Everything else passes through.
ENV KEYCLOAK_URL=http://localhost:8091/auth
ENV OIDC_AUTH_SERVER_URL=http://localhost:8080/auth/realms/acme
ENV OIDC_DISCOVERY_ENABLED=false
ENV OIDC_JWKS_PATH=http://localhost:8080/auth/realms/acme/protocol/openid-connect/certs
ENV OIDC_TOKEN_ISSUER=http://localhost:8080/auth/realms/acme
ENV PORT=8090

# Starts Keycloak and the MCP server in the background. Readiness is a separate,
# idempotent gate any consumer can block on.
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
COPY wait_for_services.sh /usr/local/bin/wait-for-services
RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/wait-for-services

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["/bin/bash"]

# DO NOT bake skills here. `bench eval run --skill-mode with-skill --skills-dir <skills-dir>` injects
# them at deploy time. Baking them in makes the without-skills run a no-op.
