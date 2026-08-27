#!/bin/bash
# Blocks until Keycloak is serving the acme realm, the mail capture server is
# accepting connections, the deployment-token proxy is running, and the MCP
# server is ready, or fails after ~180s. Installed as /usr/local/bin/wait-for-services.
#
# The container's command is started as soon as the services are launched rather
# than after they are ready, so anything that talks to them - the agent's
# session, the oracle, the verifier - can be scheduled during the few seconds
# they need to boot. Everything that depends on them waits here first.
set -uo pipefail

ACME=http://localhost:8080/auth/realms/acme/.well-known/openid-configuration
# The proxy forwards anything but the deployment-token path straight to
# Keycloak, so its root just mirrors whatever Keycloak returns there - any
# response at all (not connection-refused) means the proxy process is up.
PROXY_HEALTH=http://localhost:8091/auth/realms/acme/.well-known/openid-configuration
# The MCP server requires a bearer token on /mcp, so "ready" is a 401, not a 200.
MCP=http://localhost:8090/mcp

for _ in $(seq 1 90); do
  keycloak_up=0
  mail_up=0
  proxy_up=0
  mcp_up=0
  curl -sf "$ACME" >/dev/null 2>&1 && keycloak_up=1
  (echo > /dev/tcp/127.0.0.1/1025) >/dev/null 2>&1 && mail_up=1
  curl -sf "$PROXY_HEALTH" >/dev/null 2>&1 && proxy_up=1
  mcp_status=$(curl -s -o /dev/null -w '%{http_code}' "$MCP" 2>/dev/null || echo 000)
  [ "$mcp_status" = "401" ] && mcp_up=1
  if [ "$keycloak_up" -eq 1 ] && [ "$mail_up" -eq 1 ] && [ "$proxy_up" -eq 1 ] && [ "$mcp_up" -eq 1 ]; then
    echo "keycloak ready on :8080/auth (acme), mail capture server ready on :1025, proxy ready on :8091, mcp server ready on :8090"
    exit 0
  fi
  sleep 2
done

echo "services did not become ready within 180s (keycloak=$keycloak_up mail=$mail_up proxy=$proxy_up mcp=$mcp_up)" >&2
exit 1
