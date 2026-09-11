#!/bin/bash

# Copyright 2026 Phase Two, Inc.
# SPDX-License-Identifier: Apache-2.0

# Blocks until Keycloak is serving BOTH realms this task imports, or fails after
# ~180s. Installed as /usr/local/bin/wait-for-services.
#
# The container's command is started as soon as Keycloak is launched rather than
# after it is ready, so anything that talks to it - the agent's session, the
# oracle, the verifier - can be scheduled during the few seconds it needs to
# boot. Everything that depends on it waits here first.
set -uo pipefail

ACME=http://localhost:8080/auth/realms/acme/.well-known/openid-configuration
EVIL=http://localhost:8080/auth/realms/acme-evil/.well-known/openid-configuration

acme_up=0
evil_up=0
for _ in $(seq 1 90); do
  acme_up=0
  evil_up=0
  curl -sf "$ACME" >/dev/null 2>&1 && acme_up=1
  curl -sf "$EVIL" >/dev/null 2>&1 && evil_up=1
  if [ "$acme_up" -eq 1 ] && [ "$evil_up" -eq 1 ]; then
    echo "keycloak ready on :8080/auth (realms: acme, acme-evil)"
    exit 0
  fi
  sleep 2
done

echo "services did not become ready within 180s (acme=$acme_up acme-evil=$evil_up)" >&2
exit 1
