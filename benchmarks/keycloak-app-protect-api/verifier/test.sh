#!/bin/bash

# Copyright 2026 Phase Two, Inc.
# SPDX-License-Identifier: Apache-2.0

# Verifier script - writes reward to /logs/verifier/reward.txt (float 0.0-1.0).
# Exit 0 after writing it; nonzero exit means verifier infrastructure failure.
#
# The deliverable is the CODE at /app/api, not a running process: this script
# builds it offline and runs the jar itself, so an agent that never started the
# app (or left a stale build running) is judged on what it wrote.

mkdir -p /logs/verifier

# Keycloak (both realms) must be answering before anything is asserted.
if ! /usr/local/bin/wait-for-services > /logs/verifier/services-readiness.txt 2>&1; then
  cat /logs/verifier/services-readiness.txt >&2
  echo "0" > /logs/verifier/reward.txt
  exit 0
fi

# Stop whatever inventory-api process the agent may have left running - the
# assertions must hit the jar built from the current source, not a stale one.
pkill -f 'inventory-api-.*\.jar' 2>/dev/null
sleep 2

# Deliverable 5: the offline build still exits 0.
if ! (cd /app/api && mvn -o -DskipTests package) > /logs/verifier/build.txt 2>&1; then
  echo "offline build failed - see build.txt" >> /logs/verifier/build.txt
  tail -40 /logs/verifier/build.txt >&2
  echo "0" > /logs/verifier/reward.txt
  exit 0
fi

JAR=$(ls /app/api/target/inventory-api-*.jar 2>/dev/null | head -1)
if [ -z "$JAR" ]; then
  echo "no inventory-api jar produced by the build" >&2
  echo "0" > /logs/verifier/reward.txt
  exit 0
fi

java -jar "$JAR" > /logs/verifier/app.log 2>&1 &
APP_PID=$!
trap 'kill "$APP_PID" 2>/dev/null' EXIT

# Ready when :8085 returns a REAL http status to /healthz - Tomcat is accepting
# and dispatching. curl's -w prints 000 on connection-refused, so 000/empty means
# "not serving yet", not ready. /healthz specifically returning 200 is a scored
# assertion, not a readiness condition: an over-locked app that answers 401/403
# here still counts as "up" (it fails in pytest, where the failure is visible),
# but a port that is not listening does not.
app_up=0
for _ in $(seq 1 60); do
  code=$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8085/healthz 2>/dev/null)
  case "$code" in
    ""|000) : ;;                 # not listening yet
    *) app_up=1; break ;;         # a real HTTP response - Tomcat is serving
  esac
  sleep 2
done
if [ "$app_up" -ne 1 ]; then
  echo "app did not come up on :8085 within 90s - see app.log" >&2
  tail -40 /logs/verifier/app.log >&2
  echo "0" > /logs/verifier/reward.txt
  exit 0
fi

# /verifier is mounted read-only, so pytest's cache writes are disabled.
if python3 -m pytest -p no:cacheprovider --ctrf /logs/verifier/ctrf.json \
    /verifier/test_outputs.py -rA -v > /logs/verifier/output.txt 2>&1; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi

cat /logs/verifier/output.txt
exit 0
