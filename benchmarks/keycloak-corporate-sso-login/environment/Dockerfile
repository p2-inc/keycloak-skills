# Copyright 2026 Phase Two, Inc.
# SPDX-License-Identifier: Apache-2.0

# The real Keycloak MCP server (Quarkus), pulled pre-built from Phase Two's own
# ECR staging registry rather than vendored in git. Tracks :latest deliberately, so
# benchmarks exercise the current staging build; that means a run is reproducible
# only relative to whatever :latest pointed at. Pin a digest here when a result has
# to be reproducible later. Requires ECR auth to pull - see docs/adding-a-skill.md.
# The Keycloak MCP server stage is OPTIONAL so this benchmark is publicly
# buildable. The image lives in Phase Two's private ECR, which outside
# contributors cannot pull — a hard FROM failed their build outright with
# "403 Forbidden ... no resource-based policy allows ecr:BatchGetImage".
#
# The default is a tiny public image with an empty /deployments, so the COPY
# below lands nothing and the runtime simply has no MCP server. Phase Two
# builds pass the real one:
#
#   docker build --build-arg MCP_IMAGE=773532640636.dkr.ecr.us-west-2.amazonaws.com/mcp/staging:latest .
#
# entrypoint.sh and wait_for_services.sh both key off whether
# /opt/mcp-app/quarkus-run.jar exists, so nothing else has to stay in sync.
ARG MCP_IMAGE=alpine:3.20
FROM ${MCP_IMAGE} AS mcp-app
# No-op for the real server image (it ships /deployments already); creates an
# empty dir for the public default so the COPY always resolves.
RUN mkdir -p /deployments

# Phase Two's own Keycloak distribution: the image Phase Two deployments run.
# Until 2026-11-18 this task ran stock upstream Keycloak with native
# organizations, which Phase Two never enables; see the comment at the top of
# task.md.
#
# Pinned to one immutable build. Phase Two re-pushes the `26.8.2` tag on every
# rebuild (three builds in November 2026 alone), and each build also gets a
# permanent `26.8.2.<build>` tag. This is the build `26.8.2` pointed at on
# 2026-11-18. It bundles, already in providers/:
#   - keycloak-orgs 0.199: organizations at /realms/{realm}/orgs, linking an
#     identity provider to one (POST .../orgs/{id}/idps/link), and the
#     ext-auth-home-idp-discovery authenticator that routes by email domain.
#     0.199 also adds a REQUIRED ext-auth-org-domain-fbl-verifier to every
#     realm's "first broker login" flow (GHSA-gvcc-4vw2-6wvr): an IdP linked to
#     an organization can create an account only for an email at one of that
#     organization's domains.
#   - keycloak-atomic-auth-flows 0.4: POST /admin/realms/{realm}/authentication-flow/import
#     authors a flow and binds it in one call. Keycloak's own partialImport
#     endpoint has no handler for authentication flows and silently ignores them
#     (200 OK, nothing created), so without this extension a flow has to be built
#     by the long create-flow / add-execution / set-requirement / attach-config
#     sequence.
FROM quay.io/phasetwo/phasetwo-keycloak:26.8.2.1794965685@sha256:cbd2ff4f860ab90fa2ccf6d5fc6dd7fb5496c7c1a0397a7b243e1204b477bc82
USER root

# Wolfi (apk-based) - no python/curl/jq in the base image.
#
# util-linux-bins matters for a non-obvious reason: bench launches the agent with
#   `if setpriv --help | grep -q reuid; then setpriv --reuid=agent ...; else su -l agent -c ...; fi`
# This base image's /usr/bin/setpriv is a busybox symlink WITHOUT --reuid support, so
# bench silently falls back to `su -l`, which is a LOGIN shell and therefore RESETS the
# environment - dropping ANTHROPIC_API_KEY and the provider base URL before the agent
# starts, which surfaces only as an opaque "ACP error -32000: Authentication required".
# util-linux-bins replaces that symlink with the real setpriv, which preserves the env.
#
# findutils matters for the same class of reason: bench's with-skill deployment step
# runs `find ... -printf ...` to locate/verify injected skill files. This image's
# /usr/bin/find is a BusyBox multi-call binary with no -printf support at all
# ("find: unrecognized: -printf"), which fails the deployment outright before the
# agent ever starts (experiment_fidelity/skill_deployment_missing). findutils
# replaces it with the real GNU find.
RUN apk update && apk add --no-cache python3 py3-pip curl jq bash util-linux-bins findutils

# pytest is baked in because the sandbox runs with no network at verify time.
RUN pip install --break-system-packages --no-cache-dir \
    requests==2.32.3 pytest==8.4.1 pytest-json-ctrf==0.3.5

WORKDIR /app

# bench runs the agent as an unprivileged `agent` user and chowns its home to
# agent:agent. Unlike a Debian-based image, this Wolfi base has no such user
# (only `keycloak`), so that chown fails and the whole run errors out before the
# agent starts - create it explicitly.
RUN adduser -D -h /home/agent agent 2>/dev/null || true

# bench's verifier hardening forces --rootdir=/app; pre-create it so pytest doesn't error.
# bench's skill-injection symlinks land in /home/agent/.claude/ etc.; pre-create with permissive
# ownership so the sandbox `agent` user can write session-env there.
RUN mkdir -p /app /home/agent/.claude /home/agent/.codex /home/agent/.opencode /home/agent/.agents \
    /logs/verifier /logs/agent /logs/artifacts && \
    chown -R agent:agent /home/agent && \
    chmod -R 777 /home/agent /logs

# Two realms, imported on first start. Frozen fixtures.
#   acme        - the realm under configuration: a browser client and one internal
#                 staff account with a password. No identity provider, no
#                 organization.
#   contoso-idp - stands in for the customer's own identity provider, which they
#                 operate. Holds the federation client and the customer's staff.
COPY acme-realm.json /opt/keycloak/data/import/acme-realm.json
COPY contoso-idp-realm.json /opt/keycloak/data/import/contoso-idp-realm.json

# Admin credentials, and the federation details the customer's IT team handed over.
COPY admin_credentials.txt /root/admin_credentials.txt
COPY corporate_idp_details.txt /root/corporate_idp_details.txt

# The real Keycloak MCP server (Quarkus), pulled from the mcp-app build stage
# above rather than vendored. Present in BOTH the with-skill and no-skill arms:
# it is environment, not skill, so the comparison measures skill effect on top
# of identical tool access, not tool access itself.
COPY --from=mcp-app /deployments /opt/mcp-app

# The deployment-token proxy, the same file every other MCP-wired task ships.
# The MCP tools this task needs (createDeploymentOrganization,
# linkIdentityProviderToOrganization, importAuthenticationFlow,
# bindRealmAuthenticationFlow, ...) are written for Phase Two's real product
# shape: a control-plane realm plus a *separate*, remotely-hosted "deployment"
# they operate on, reached by exchanging a deploymentId at
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
# The base image sets KC_HTTP_ENABLED=false (production expects TLS in front).
ENV KC_HTTP_ENABLED=true
# Keycloak's native, in-core Organizations feature is off, as on every Phase
# Two deployment: their Helm values and phasetwo-keycloak's own Dockerfile set
# exactly this. The published image does not, so it is set here. With it off,
# /admin/realms/{realm}/organizations does not exist and the realm has no
# organizationsEnabled switch; organizations come only from keycloak-orgs.
ENV KC_FEATURES_DISABLED=organization

# The MCP server, in-container. Bearer tokens the agent presents are validated
# against Keycloak's real JWKS - see the comment in task.md for why the token
# itself is a fixed fixture rather than minted at boot.
# KEYCLOAK_URL points at the deployment-token proxy (:8091), not at Keycloak
# (:8080) directly: it is the MCP server's only route to any Keycloak, so this is
# what makes the synthetic deployment-token exchange reachable. Everything else
# passes through.
ENV KEYCLOAK_URL=http://localhost:8091/auth
ENV OIDC_AUTH_SERVER_URL=http://localhost:8080/auth/realms/acme
ENV OIDC_DISCOVERY_ENABLED=false
ENV OIDC_JWKS_PATH=http://localhost:8080/auth/realms/acme/protocol/openid-connect/certs
ENV OIDC_TOKEN_ISSUER=http://localhost:8080/auth/realms/acme
ENV PORT=8090

# Starts Keycloak, the proxy and the MCP server in the background. Readiness is
# a separate, idempotent gate any consumer can block on.
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
COPY wait_for_services.sh /usr/local/bin/wait-for-services
RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/wait-for-services

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["/bin/bash"]

# DO NOT bake skills here. `bench eval run --skill-mode with-skill --skills-dir <skills-dir>` injects
# them at deploy time. Baking them in makes the without-skills run a no-op.
