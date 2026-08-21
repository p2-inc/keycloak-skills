# The real Keycloak MCP server (Quarkus), pulled pre-built from Phase Two's own
# registry. Tracks :latest deliberately - the server is developed alongside these
# benchmarks, and a digest pin silently held this task on a build that predated
# several tool fixes (notably getAuthenticationBindings' client-override
# resolution), so the benchmark measured a server nobody was shipping any more.
#
# The tradeoff is explicit: a run's result can now change without this task
# changing. If you need a reproducible historical run, pin the digest back here.
# Requires `docker login quay.io` with Phase Two Quay credentials.
FROM 773532640636.dkr.ecr.us-west-2.amazonaws.com/mcp/staging:latest AS mcp-app

# Phase Two's own Keycloak distribution. This single base image already bundles BOTH
# extensions this task needs as real Maven dependencies of phasetwo-module (see
# phasetwo-keycloak's pom.xml: keycloak-orgs and keycloak-magic-link are both regular
# dependencies baked into phasetwo-bundle, not something added here):
#   - io.phasetwo.keycloak-keycloak-orgs - the REAL p2-inc keycloak-orgs extension,
#     providing organizations, membership, and the `ext-select-org` authenticator.
#   - keycloak-magic-link - the REAL p2-inc keycloak-magic-link provider, providing
#     `ext-magic-form`, `ext-auth-username-auth-note`, and the action-token handling
#     the magic-link ceremony needs.
# Plain upstream Keycloak has neither - there is no native-Keycloak equivalent for
# either half of this task.
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
#
# findutils matters for the same class of reason: bench's with-skill deployment step
# runs `find ... -printf ...` to locate/verify injected skill files. This image's
# /usr/bin/find is a BusyBox multi-call binary with no -printf support at all
# ("find: unrecognized: -printf"), which fails the deployment outright before the
# agent ever starts (experiment_fidelity/skill_deployment_missing). findutils
# replaces it with the real GNU find.
RUN apk update && apk add --no-cache python3 py3-pip curl jq bash util-linux-bins findutils

# pytest is baked in because the sandbox runs with no network at verify time.
# aiosmtpd backs the local outgoing-mail capture server (same as the plain
# magic-link task).
RUN pip install --break-system-packages --no-cache-dir \
    requests==2.32.3 aiosmtpd==1.4.6 pytest==8.4.1 pytest-json-ctrf==0.3.5

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
    /logs/verifier /logs/agent /logs/artifacts /var/mail-capture && \
    chown -R agent:agent /home/agent && \
    chmod -R 777 /home/agent /logs /var/mail-capture

# The realm the agent configures, imported on first start. Frozen fixture: two
# staff accounts with passwords AND verified emails (priya, morgan), a public
# browser client, and no organization created yet. Reused as-is from
# keycloak-org-restrict-login - magic-link login doesn't need a password on the
# account, only that it already exists with a verified email, which this fixture
# already provides. Includes the same fixed RSA signing key and mcp-operator user
# as the other MCP-wired tasks, for the MCP server's crafted token validation.
COPY acme-realm.json /opt/keycloak/data/import/acme-realm.json

# Admin credentials, and connection details for the local mail-capture server.
COPY admin_credentials.txt /root/admin_credentials.txt
COPY mail_server_details.txt /root/mail_server_details.txt

# The mail capture server itself - fixed infrastructure, not something to configure.
COPY mail_capture_server.py /opt/mail/mail_capture_server.py

# The real Keycloak MCP server (Quarkus), pulled from the mcp-app build stage
# above. Present in BOTH the with-skill and no-skill arms: it is environment,
# not skill, so the comparison measures skill effect on top of identical tool
# access, not tool access itself.
COPY --from=mcp-app /deployments /opt/mcp-app

# The deployment-token proxy: AuthenticationFlowTools' tools (importAuthenticationFlow,
# listAuthenticationFlows, bindRealmAuthenticationFlow, ...) and the org tools are
# written for Phase Two's real product shape - a control-plane realm plus a *separate*,
# remotely-hosted "deployment" they operate on, reached by exchanging a deploymentId at
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

# Required for keycloak-magic-link's MagicLink.sendMagicLinkEmail to work at all -
# without this, EmailTemplateProvider resolves to null and every send crashes with
# an NPE (org.keycloak.email.EmailTemplateProvider.setRealm on a null provider),
# discovered by actually driving a login against this image rather than assuming
# the base image's defaults were enough. Matches the real phasetwo-keycloak
# Dockerfile's own runtime config for the same provider.
ENV KC_SPI_EMAIL_TEMPLATE_PROVIDER=freemarker-plus-mustache
ENV KC_SPI_EMAIL_TEMPLATE_FREEMARKER_PLUS_MUSTACHE_ENABLED=true

# The MCP server, in-container, pointed at the deployment-token proxy (:8091), not
# Keycloak (:8080), directly - KEYCLOAK_URL is the MCP server's only route to any
# Keycloak, so this is what makes the synthetic deployment-token exchange reachable.
# Everything else passes through. Bearer tokens the agent presents are validated
# against Keycloak's real JWKS - same fixed-key fixture as the other MCP-wired tasks.
ENV KEYCLOAK_URL=http://localhost:8091/auth
ENV OIDC_AUTH_SERVER_URL=http://localhost:8080/auth/realms/acme
ENV OIDC_DISCOVERY_ENABLED=false
ENV OIDC_JWKS_PATH=http://localhost:8080/auth/realms/acme/protocol/openid-connect/certs
ENV OIDC_TOKEN_ISSUER=http://localhost:8080/auth/realms/acme
ENV PORT=8090

# Starts Keycloak, the mail capture server, the deployment-token proxy, and the MCP
# server in the background. Readiness is a separate, idempotent gate any consumer
# can block on.
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
COPY wait_for_services.sh /usr/local/bin/wait-for-services
RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/wait-for-services

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["/bin/bash"]

# DO NOT bake skills here. `bench eval run --skill-mode with-skill --skills-dir <skills-dir>` injects
# them at deploy time. Baking them in makes the without-skills run a no-op.
