#!/bin/bash

# Copyright 2026 Phase Two, Inc.
# SPDX-License-Identifier: Apache-2.0

# Launches Keycloak, mail capture server, deployment-token proxy, and MCP server,
# then hands straight over to the container's command. It deliberately does not
# block on readiness: the sandbox runs commands via exec regardless of what this
# script is doing, so gating here would buy nothing. Callers wait via
# /usr/local/bin/wait-for-services instead.
#
# Native Keycloak organizations support is NOT enabled here (no --features=organization).
# This task exercises the real p2-inc keycloak-orgs extension baked into the
# base image instead - Phase Two's own product never uses the native feature.
set -m

/opt/keycloak/bin/kc.sh start-dev \
  --http-port=8080 \
  --http-relative-path=/auth \
  --import-realm \
  > /var/log/keycloak.log 2>&1 &

python3 /opt/mail/mail_capture_server.py > /var/log/mail-capture.log 2>&1 &

# The deployment-token proxy sits between the MCP server and Keycloak - see the
# Dockerfile for why. It forwards to Keycloak, so it can start immediately.
python3 /opt/mcp/deployment_token_proxy.py > /var/log/deployment-token-proxy.log 2>&1 &

# The MCP server fetches JWKS from Keycloak and routes admin calls through the
# proxy (KEYCLOAK_URL), so it has to come up after both are actually serving -
# backgrounded as its own subshell so this script still returns immediately;
# wait-for-services is what callers block on.
(
  for _ in $(seq 1 90); do
    curl -sf http://localhost:8080/auth/realms/acme/.well-known/openid-configuration \
      >/dev/null 2>&1 && break
    sleep 2
  done
  # -Dquarkus.management.port: phasetwo-keycloak (26.6.4+) runs its own Quarkus management
  # interface on :9000, and this MCP server is also Quarkus - co-located in one container
  # they collide and the MCP server dies with
  #   IllegalStateException: Unable to start the management interface on 0.0.0.0:9000
  #   Caused by: java.net.BindException: Address already in use
  # which surfaces only as "services did not become ready within 180s" from
  # wait-for-services, because /mcp never answers. Set with -D on THIS jvm, not as an env
  # var: QUARKUS_MANAGEMENT_PORT would move BOTH apps and reproduce the clash.
  java -Dquarkus.management.port=9001 -jar /opt/mcp-app/quarkus-run.jar > /var/log/mcp-server.log 2>&1
) &

exec "$@"
