#!/bin/bash

# Copyright 2026 Phase Two, Inc.
# SPDX-License-Identifier: Apache-2.0

# Launches Keycloak, the deployment-token proxy, and the MCP server, then hands
# straight over to the container's command. It deliberately does not block on
# readiness: the sandbox runs commands via exec regardless of what this script
# is doing, so gating here would buy nothing. Callers wait via
# /usr/local/bin/wait-for-services instead.
set -m

/opt/keycloak/bin/kc.sh start-dev \
  --http-port=8080 \
  --http-relative-path=/auth \
  --import-realm \
  > /var/log/keycloak.log 2>&1 &

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
  # -Dquarkus.management.port: this MCP server is Quarkus, and so is Keycloak from 25
  # onward - co-located in one container their management interfaces both want :9000 and
  # the MCP server dies with BindException, surfacing only as "services did not become
  # ready" because /mcp never answers. Set with -D on THIS jvm: QUARKUS_MANAGEMENT_PORT
  # as an env var would move BOTH apps and reproduce the clash. Matches the other
  # MCP-wired benchmarks in this repo.
  /opt/java21/bin/java -Dquarkus.management.port=9001 -jar /opt/mcp-app/quarkus-run.jar > /var/log/mcp-server.log 2>&1
) &

exec "$@"
