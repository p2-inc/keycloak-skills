#!/bin/bash

# Copyright 2026 Phase Two, Inc.
# SPDX-License-Identifier: Apache-2.0

# Verifier script - writes reward to /logs/verifier/reward.txt (float 0.0-1.0).
# Exit 0 after writing it; nonzero exit means verifier infrastructure failure.

mkdir -p /logs/verifier

# Keycloak and the MCP server must be answering before anything is asserted.
if ! /usr/local/bin/wait-for-services > /logs/verifier/services-readiness.txt 2>&1; then
  cat /logs/verifier/services-readiness.txt >&2
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
