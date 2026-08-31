#!/bin/bash

# Copyright 2026 Phase Two, Inc.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail
/usr/local/bin/wait-for-services
python3 "$(dirname "$0")/solve.py"
