#!/bin/bash

# Copyright 2026 Phase Two, Inc.
# SPDX-License-Identifier: Apache-2.0

# Blocks until Keycloak is serving the acme and contoso-idp realms AND the MCP
# server is answering, or fails after ~180s. Installed as /usr/local/bin/wait-for-services.
set -uo pipefail

ACME=http://localhost:8080/auth/realms/acme/.well-known/openid-configuration
CONTOSO=http://localhost:8080/auth/realms/contoso-idp/.well-known/openid-configuration
# The deployment-token proxy forwards everything it doesn't intercept, so serving
# the realm's discovery document proves it's up AND reaching Keycloak behind it.
PROXY_HEALTH=http://localhost:8091/auth/realms/acme/.well-known/openid-configuration
# No health endpoint is exposed; /mcp answering 401 (auth-enforced, not
# connection-refused) is what proves the server is actually up.
MCP=http://localhost:8090/mcp

for _ in $(seq 1 90); do
  mcp_status=$(curl -s -o /dev/null -w '%{http_code}' "$MCP" 2>/dev/null || echo 000)
  if curl -sf "$ACME" >/dev/null 2>&1 && curl -sf "$CONTOSO" >/dev/null 2>&1 \
      && curl -sf "$PROXY_HEALTH" >/dev/null 2>&1 \
      && [ "$mcp_status" = "401" ]; then
    echo "keycloak ready on :8080/auth (acme, contoso-idp), proxy ready on :8091, mcp server ready on :8090"
    exit 0
  fi
  sleep 2
done

echo "services did not become ready within 180s" >&2
exit 1
