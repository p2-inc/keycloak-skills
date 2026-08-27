#!/bin/bash
set -euo pipefail
/usr/local/bin/wait-for-services
python3 "$(dirname "$0")/solve.py"
