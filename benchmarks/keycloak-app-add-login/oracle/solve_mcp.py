#!/usr/bin/env python3

# Copyright 2026 Phase Two, Inc.
# SPDX-License-Identifier: Apache-2.0

"""MCP-tooling oracle for keycloak-app-add-login.

The sibling solve.py drives the Admin REST API. This one drives the **Keycloak MCP
server** in-container, so the `mcp` arm has a free, oracle-verified path before any
paid agent runs on it - the repo's standing policy, applied per tooling arm rather
than once per task.

It exists because of a real failure: the benchmark image tracked `mcp/staging:latest`,
a locally cached copy of that tag was two days stale, and it silently lacked
`updateOidcClient` - the one tool this task needs. Nothing caught it, because no
oracle had ever called an MCP tool. tools/list below is the assertion that would have.
"""

import json
import sys
import urllib.request

sys.path.insert(0, "/oracle")
from solve import wire_app  # identical app half; tooling must not change app code

MCP_URL = "http://localhost:8090/mcp"
DEPLOYMENT_ID = "acme"          # the proxy answers the token exchange for any id
DEPLOYMENT_REALM = "acme"
CLIENT_ID = "acme-portal"
APP_ORIGIN = "http://localhost:5173"
APP_REDIRECT = "http://localhost:5173/"   # trailing slash: oidc-spa returns to the base URL

# Fixture bearer, identical to the one task.md hands the agent. Not a secret: it is
# signed by the fixed key baked into acme-realm.json and scoped to this throwaway realm.
TOKEN = "eyJhbGciOiJSUzI1NiIsImtpZCI6Imx2N1o4T1VPN1V0SlE3bU1XY01pM3lKVkFfbXJGRmFNQm84WU8zRE9BeWsiLCJ0eXAiOiJKV1QifQ.eyJpc3MiOiJodHRwOi8vbG9jYWxob3N0OjgwODAvYXV0aC9yZWFsbXMvYWNtZSIsInN1YiI6Ijc3NGMzMWVjLTE2MDEtNTNlOS05ZjFkLWZiMTBkNjFlN2NhNyIsInR5cCI6IkJlYXJlciIsImF6cCI6Im1jcC1iZW5jaC1jbGkiLCJhY3IiOiIxIiwicmVhbG1fYWNjZXNzIjp7InJvbGVzIjpbImRlZmF1bHQtcm9sZXMtYWNtZSIsIm9mZmxpbmVfYWNjZXNzIiwidW1hX2F1dGhvcml6YXRpb24iXX0sInJlc291cmNlX2FjY2VzcyI6eyJyZWFsbS1tYW5hZ2VtZW50Ijp7InJvbGVzIjpbInZpZXctaWRlbnRpdHktcHJvdmlkZXJzIiwidmlldy1yZWFsbSIsIm1hbmFnZS1pZGVudGl0eS1wcm92aWRlcnMiLCJpbXBlcnNvbmF0aW9uIiwicmVhbG0tYWRtaW4iLCJjcmVhdGUtY2xpZW50IiwibWFuYWdlLXVzZXJzIiwicXVlcnktcmVhbG1zIiwidmlldy1hdXRob3JpemF0aW9uIiwicXVlcnktY2xpZW50cyIsInF1ZXJ5LXVzZXJzIiwibWFuYWdlLWV2ZW50cyIsIm1hbmFnZS1yZWFsbSIsInZpZXctZXZlbnRzIiwidmlldy11c2VycyIsInZpZXctY2xpZW50cyIsIm1hbmFnZS1hdXRob3JpemF0aW9uIiwibWFuYWdlLWNsaWVudHMiLCJxdWVyeS1ncm91cHMiXX0sImFjY291bnQiOnsicm9sZXMiOlsibWFuYWdlLWFjY291bnQiLCJtYW5hZ2UtYWNjb3VudC1saW5rcyIsInZpZXctcHJvZmlsZSJdfX0sInNjb3BlIjoicHJvZmlsZSBlbWFpbCIsImVtYWlsX3ZlcmlmaWVkIjp0cnVlLCJuYW1lIjoiTUNQIE9wZXJhdG9yIiwicHJlZmVycmVkX3VzZXJuYW1lIjoibWNwLW9wZXJhdG9yIiwiZ2l2ZW5fbmFtZSI6Ik1DUCIsImZhbWlseV9uYW1lIjoiT3BlcmF0b3IiLCJlbWFpbCI6Im1jcC1vcGVyYXRvckBhY21lLmV4YW1wbGUiLCJpYXQiOjE3NjcyMjU2MDAsImV4cCI6NDg1OTc0MDgwMCwianRpIjoic2tpbGxzYmVuY2gtZml4ZWQtbWNwLXRva2VuIn0.hthr7rjZpSB04KsoxUR06IRV7Vy4aGNAWA4uwjDhB6M5qs3WC9b8BuAH1RDtm76nxz8mz39T4NAgy-zjFbGkK9buj_hL53YpkATwkU2YETYwXHK_f6PoGcIYO-l4vaiIXrYjUo6LoXCCJX14naak_Wt7CtXYtWDyzdR6vr9HoTtIlZRsd3iXsLUNU_pam5bszEKcl0s7FJK4GRlmWcyQymA-WqNXFpgWhLSmZWAMXpFTTKLCvGr8yqSs0Hi260zfxgo8nnEQuIYA4iFV0MH0D8oMQH64iMUyyrTdxTXBMaWtVbWLvPup7h8zWJXWgg3Iab5pvNt1yxpdo2KW0AJjAg"

_id = 0
_session = None   # streamable-HTTP session id, issued by initialize


def rpc(method, params=None, notify=False):
    """Minimal MCP-over-HTTP client. Handles both plain JSON and SSE responses.

    The transport is session-oriented: `initialize` returns an `Mcp-Session-Id`
    header that must be echoed on every subsequent request, or the server rejects
    the call with "The first message from the client must be initialize".
    """
    global _id, _session
    body = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        body["params"] = params
    if not notify:
        _id += 1
        body["id"] = _id
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if _session:
        headers["Mcp-Session-Id"] = _session
    req = urllib.request.Request(
        MCP_URL, data=json.dumps(body).encode(), headers=headers, method="POST"
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        if not _session:
            _session = resp.headers.get("Mcp-Session-Id") or resp.headers.get("mcp-session-id")
        raw = resp.read().decode()
    if notify or not raw.strip():
        return None
    # Streamable-HTTP may frame the reply as server-sent events.
    if raw.lstrip().startswith("event:") or raw.lstrip().startswith("data:"):
        for line in raw.splitlines():
            if line.startswith("data:"):
                raw = line[5:].strip()
                break
    out = json.loads(raw)
    if "error" in out:
        sys.exit(f"oracle(mcp): {method} failed: {out['error']}")
    return out.get("result")


def call_tool(name, args):
    res = rpc("tools/call", {"name": name, "arguments": args})
    parts = res.get("content") or []
    text = "".join(p.get("text", "") for p in parts if p.get("type") == "text")
    if res.get("isError"):
        sys.exit(f"oracle(mcp): tool {name} returned an error: {text}")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}
    if isinstance(payload, dict) and payload.get("error"):
        sys.exit(f"oracle(mcp): tool {name} reported: {payload['error']}")
    return payload


def main():
    rpc("initialize", {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "oracle-mcp", "version": "1.0"},
    })
    rpc("notifications/initialized", {}, notify=True)

    # The assertion that a stale image would have failed.
    names = {t["name"] for t in (rpc("tools/list") or {}).get("tools", [])}
    for required in ("listClients", "updateOidcClient"):
        if required not in names:
            sys.exit(
                f"oracle(mcp): the MCP server does not expose {required!r}. "
                f"The pinned image is too old for this task - see the digest note "
                f"in environment/Dockerfile. Exposed client tools: "
                f"{sorted(n for n in names if 'lient' in n)}"
            )
    print(f"oracle(mcp): tools/list ok; updateOidcClient present ({len(names)} tools)")

    before = call_tool("listClients", {
        "deploymentId": DEPLOYMENT_ID, "deploymentRealm": DEPLOYMENT_REALM})
    print(f"oracle(mcp): listClients -> {json.dumps(before)[:200]}")

    # Repair the stale client. updateOidcClient read-merges, so the acme-department
    # protocol mapper survives - that is the property the verifier checks.
    call_tool("updateOidcClient", {
        "deploymentId": DEPLOYMENT_ID,
        "deploymentRealm": DEPLOYMENT_REALM,
        "clientId": CLIENT_ID,
        # Both lists REPLACE: send the full intended set, not just the addition.
        "redirectUris": f"http://localhost:9999/callback,{APP_REDIRECT}",
        "webOrigins": APP_ORIGIN,
    })
    print("oracle(mcp): updateOidcClient ok")

    wire_app()
    print("oracle(mcp): done")


if __name__ == "__main__":
    main()
