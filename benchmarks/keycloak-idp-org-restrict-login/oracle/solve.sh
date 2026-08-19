#!/bin/bash
# Oracle solution - demonstrates the task is solvable.
# Used by: bench eval run --agent oracle --tasks-dir tasks/keycloak-idp-org-restrict-login
set -euo pipefail

# The sandbox may exec this within a second of container start, before Keycloak
# and the MCP server have finished booting.
/usr/local/bin/wait-for-services

python3 /oracle/solve.py
