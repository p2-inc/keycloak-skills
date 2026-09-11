#!/bin/bash

# Copyright 2026 Phase Two, Inc.
# SPDX-License-Identifier: Apache-2.0

# Launches Keycloak, then hands straight over to the container's command. It
# deliberately does not block on readiness: the sandbox runs commands via exec
# regardless of what this script is doing, so gating here would buy nothing.
# Callers wait via /usr/local/bin/wait-for-services instead.
#
# The Spring Boot app is NOT started here - building and running it is the
# agent's (and the verifier's) business, not the environment's.
set -m

/opt/keycloak/bin/kc.sh start-dev \
  --http-port=8080 \
  --http-relative-path=/auth \
  --import-realm \
  > /var/log/keycloak.log 2>&1 &

exec "$@"
