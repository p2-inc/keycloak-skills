#!/usr/bin/env python3
# Copyright 2026 Phase Two, Inc.
# SPDX-License-Identifier: Apache-2.0
"""Check that registry/server.json agrees with the plugin manifests.

Hard failures:
  - a plugin manifest declares an MCP server URL that is not listed in the
    "remotes" of registry/server.json (the listing would point at a different
    endpoint than the one the plugins install);
  - the registry description is longer than the registry's 100-character limit.

Soft warning: the "version" in server.json differs from the plugin version.
The registry rejects a version it already has, so drift is allowed, but it is
worth seeing.

Standard library only. Run from anywhere: python3 scripts/check-registry.py
"""
import json
import pathlib
import sys

DESCRIPTION_LIMIT = 100

root = pathlib.Path(__file__).resolve().parent.parent
plugin = root / "plugins" / "phasetwo"
server = json.loads((root / "registry" / "server.json").read_text())
errors = []

registry_urls = {r.get("url") for r in server.get("remotes", [])}
if not registry_urls:
    errors.append("registry/server.json has no remotes")

# Every manifest that declares an MCP server. Only the URL is compared; each
# client keeps its own auth settings.
manifests = [
    ".mcp.json",
    ".claude-plugin/plugin.json",
    ".codex-plugin/plugin.json",
    ".cursor-plugin/plugin.json",
]
for name in manifests:
    data = json.loads((plugin / name).read_text())
    for key, entry in data.get("mcpServers", {}).items():
        if entry.get("url") not in registry_urls:
            errors.append(
                f"plugins/phasetwo/{name}: mcpServers.{key}.url {entry.get('url')!r} "
                f"is not in registry/server.json remotes {sorted(registry_urls)}"
            )

description = server.get("description", "")
if len(description) > DESCRIPTION_LIMIT:
    errors.append(
        f"registry/server.json description is {len(description)} characters; "
        f"the registry allows {DESCRIPTION_LIMIT}"
    )

plugin_version = json.loads((plugin / ".claude-plugin/plugin.json").read_text())["version"]
if server.get("version") != plugin_version:
    print(
        f"::warning file=registry/server.json::server.json version {server.get('version')} "
        f"differs from plugin version {plugin_version}"
    )

for e in errors:
    print(f"::error::{e}")
print("registry manifest check:", "FAILED" if errors else "ok")
sys.exit(1 if errors else 0)
