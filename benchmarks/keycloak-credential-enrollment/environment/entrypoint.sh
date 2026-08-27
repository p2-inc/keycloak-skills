#!/bin/bash
# Launches Keycloak, mail capture server, deployment-token proxy, and MCP server,
# then hands straight over to the container's command. It deliberately does not
# block on readiness: the sandbox runs commands via exec regardless of what this
# script is doing, so gating here would buy nothing. Callers wait via
# /usr/local/bin/wait-for-services instead.
set -m

/opt/keycloak/bin/kc.sh start-dev \
  --http-port=8080 \
  --http-relative-path=/auth \
  --import-realm \
  > /var/log/keycloak.log 2>&1 &

python3 /opt/mail/mail_capture_server.py > /var/log/mail-capture.log 2>&1 &

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
  /opt/java21/bin/java -jar /opt/mcp-app/quarkus-run.jar > /var/log/mcp-server.log 2>&1
) &

exec "$@"
