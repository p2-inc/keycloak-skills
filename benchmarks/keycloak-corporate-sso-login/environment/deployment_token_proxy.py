#!/usr/bin/env python3

# Copyright 2026 Phase Two, Inc.
# SPDX-License-Identifier: Apache-2.0

"""A transparent proxy in front of Keycloak, with one path intercepted.

The Keycloak MCP server's flow-binding tools (bindRealmAuthenticationFlow,
listAuthenticationFlows, bindIdpBrokerLoginFlow, linkIdentityProviderToOrganization,
...) are written for Phase Two's real product shape: a control-plane realm the
caller authenticates to, and a *separate*, remotely-hosted Keycloak "deployment"
those tools actually operate on. Reaching a deployment means exchanging a
deploymentId for {baseUrl, accessToken} via

    POST /realms/{realm}/deployments/{deploymentId}/token

which only the real Phase Two clusters/deployments backend can answer.

This sandbox has no such backend, and no separate deployment - there is one
realm, "acme", and that IS what the deployment-scoped tools should end up
touching. So this proxy sits at KEYCLOAK_URL (the MCP server's only route to
any Keycloak) and answers that one path itself, saying "the deployment lives
right here", with a freshly minted, always-valid admin token. Everything else
passes through untouched to the real Keycloak underneath.

This does not change what the MCP tools claim to do or how they behave -
bindRealmAuthenticationFlow still ends up PUTting the realm representation,
listAuthenticationFlows still GETs the flow list - it only answers the one
piece of routing indirection this sandbox has no real backend for.
"""

import http.client
import json
import re
import sys
import urllib.request

LISTEN_PORT = 8091
KEYCLOAK_HOST = "localhost"
KEYCLOAK_PORT = 8080
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin_change_me"

DEPLOYMENT_TOKEN_RE = re.compile(r"^/auth/realms/[^/]+/deployments/[^/]+/token$")


def mint_admin_token():
    """A real, freshly issued Keycloak admin token - not a stand-in."""
    body = "grant_type=password&client_id=admin-cli&username={}&password={}".format(
        ADMIN_USERNAME, ADMIN_PASSWORD
    )
    req = urllib.request.Request(
        f"http://{KEYCLOAK_HOST}:{KEYCLOAK_PORT}/auth/realms/master/protocol/openid-connect/token",
        data=body.encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())["access_token"]


from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class ProxyHandler(BaseHTTPRequestHandler):
    server_version = "deployment-token-proxy/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _handle(self, method):
        if DEPLOYMENT_TOKEN_RE.match(self.path):
            self._answer_deployment_token()
            return
        self._forward(method)

    def _answer_deployment_token(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        try:
            token = mint_admin_token()
        except Exception as exc:  # noqa: BLE001 - surface as a clear 502
            body = json.dumps({"error": f"could not mint a deployment token: {exc}"}).encode()
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        payload = json.dumps(
            {
                "base_url": f"http://{KEYCLOAK_HOST}:{KEYCLOAK_PORT}/auth",
                "access_token": token,
                "token_type": "Bearer",
                "expires_in": 300,
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _forward(self, method):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None

        conn = http.client.HTTPConnection(KEYCLOAK_HOST, KEYCLOAK_PORT, timeout=30)
        forward_headers = {
            k: v for k, v in self.headers.items() if k.lower() not in ("host", "content-length")
        }
        try:
            conn.request(method, self.path, body=body, headers=forward_headers)
            upstream = conn.getresponse()
            upstream_body = upstream.read()
        except Exception as exc:  # noqa: BLE001 - surface as a clear 502
            payload = json.dumps({"error": f"upstream Keycloak unreachable: {exc}"}).encode()
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        finally:
            conn.close()

        self.send_response(upstream.status)
        for key, value in upstream.getheaders():
            if key.lower() in ("transfer-encoding", "connection"):
                continue
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(upstream_body)

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PUT(self):
        self._handle("PUT")

    def do_DELETE(self):
        self._handle("DELETE")

    def do_PATCH(self):
        self._handle("PATCH")


def main():
    sys.stderr.write(
        f"deployment-token proxy on :{LISTEN_PORT}, forwarding to "
        f"{KEYCLOAK_HOST}:{KEYCLOAK_PORT}, intercepting .../deployments/*/token\n"
    )
    ThreadingHTTPServer(("0.0.0.0", LISTEN_PORT), ProxyHandler).serve_forever()


if __name__ == "__main__":
    main()
