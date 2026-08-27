#!/usr/bin/env python3
"""Reference solution for keycloak-app-add-login.

Derived from plugins/phasetwo/skills/securing-apps/references/framework-react.md,
not the other way round: the shipped skill describes this procedure, and this file
proves the procedure actually works.

Two halves:
  1. Repair the stale `acme-portal` client, by read-merge-PUT so the acme-department
     protocol mapper survives. Keycloak's client PUT replaces the whole
     representation; a hand-built body destroys anything it omits.
  2. Wire oidc-spa into the React skeleton at /app/frontend.
"""

import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://localhost:8080/auth"
REALM = "acme"
CLIENT_ID = "acme-portal"
APP_ORIGIN = "http://localhost:5173"
# oidc-spa redirects back to the app's base URL, so the registered redirect URI
# ends with a trailing slash. Without it Keycloak rejects the callback outright.
APP_REDIRECT = "http://localhost:5173/"
FRONTEND = "/app/frontend"


def _req(method, url, token=None, data=None, form=False):
    headers = {}
    body = None
    if data is not None:
        if form:
            body = urllib.parse.urlencode(data).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            body = json.dumps(data).encode()
            headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
        return resp.status, (json.loads(raw) if raw else None)


def admin_token():
    creds = {}
    with open("/root/admin_credentials.txt") as fh:
        for line in fh:
            if ":" in line:
                k, _, v = line.partition(":")
                creds[k.strip().lower()] = v.strip()
    user = creds.get("username") or creds.get("user") or "admin"
    pwd = creds.get("password") or "admin_change_me"
    _, tok = _req(
        "POST",
        f"{BASE}/realms/master/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": user,
            "password": pwd,
        },
        form=True,
    )
    return tok["access_token"]


def fix_client(token):
    """Read-merge-PUT. Never build the representation by hand."""
    _, found = _req(
        "GET",
        f"{BASE}/admin/realms/{REALM}/clients?clientId={CLIENT_ID}",
        token=token,
    )
    if not found:
        sys.exit(f"oracle: no client {CLIENT_ID} in realm {REALM}")
    uuid = found[0]["id"]

    # 1. READ the whole current representation.
    _, client = _req(
        "GET", f"{BASE}/admin/realms/{REALM}/clients/{uuid}", token=token
    )
    before_mappers = sorted(m["name"] for m in client.get("protocolMappers") or [])

    # 2. MERGE. Append to the existing lists rather than replacing them, so an
    #    older deployment's callback keeps working.
    client["redirectUris"] = sorted(
        set(client.get("redirectUris") or []) | {APP_REDIRECT}
    )
    # Web origins are a SEPARATE setting from redirect URIs. Registering only the
    # redirect URI yields a client that passes every server-side test and fails in
    # a real browser at the token call, on CORS.
    client["webOrigins"] = sorted(set(client.get("webOrigins") or []) | {APP_ORIGIN})
    client["publicClient"] = True
    client["standardFlowEnabled"] = True
    attrs = client.setdefault("attributes", {})
    attrs["pkce.code.challenge.method"] = "S256"

    # 3. PUT the whole thing back.
    status, _ = _req(
        "PUT", f"{BASE}/admin/realms/{REALM}/clients/{uuid}", token=token, data=client
    )
    if status >= 300:
        sys.exit(f"oracle: client PUT failed with {status}")

    # Confirm the merge preserved what it had to.
    _, after = _req("GET", f"{BASE}/admin/realms/{REALM}/clients/{uuid}", token=token)
    after_mappers = sorted(m["name"] for m in after.get("protocolMappers") or [])
    if after_mappers != before_mappers:
        sys.exit(
            f"oracle: protocol mappers changed {before_mappers} -> {after_mappers}"
        )
    print(f"oracle: client repaired; mappers intact {after_mappers}")


OIDC_TS = '''import { oidcSpa } from "oidc-spa/react-spa";
import { z } from "zod";

export const {
    bootstrapOidc,
    useOidc,
    getOidc,
    withLoginEnforced,
    OidcInitializationGate
} = oidcSpa
    .withExpectedDecodedIdTokenShape({
        decodedIdTokenSchema: z.object({
            sub: z.string(),
            name: z.string().optional(),
            email: z.string().optional(),
            preferred_username: z.string().optional()
        })
    })
    .createUtils();

bootstrapOidc({
    implementation: "real",
    issuerUri: "http://localhost:8080/auth/realms/acme",
    clientId: "acme-portal"
});

export const fetchWithAuth: typeof fetch = async (input, init) => {
    const oidc = await getOidc();
    if (oidc.isUserLoggedIn) {
        const accessToken = await oidc.getAccessToken();
        const headers = new Headers(init?.headers);
        headers.set("Authorization", `Bearer ${accessToken}`);
        (init ??= {}).headers = headers;
    }
    return fetch(input, init);
};
'''

MAIN_TSX = '''import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./App";
import { OidcInitializationGate } from "./oidc";

ReactDOM.createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
        <OidcInitializationGate>
            <App />
        </OidcInitializationGate>
    </React.StrictMode>
);
'''

APP_TSX = '''import { useOidc } from "./oidc";

function LoginButton() {
    const { login } = useOidc({ assert: "user not logged in" });
    return <button onClick={() => login()}>Log in</button>;
}

function Profile() {
    const { decodedIdToken, logout } = useOidc({ assert: "user logged in" });
    return (
        <>
            <p>
                Signed in as{" "}
                <strong>{decodedIdToken.preferred_username ?? decodedIdToken.sub}</strong>
            </p>
            <button onClick={() => logout({ redirectTo: "home" })}>Log out</button>
        </>
    );
}

export function App() {
    const { isUserLoggedIn } = useOidc();
    return (
        <main>
            <h1>Acme Portal</h1>
            {isUserLoggedIn ? <Profile /> : <LoginButton />}
        </main>
    );
}
'''


def wire_app():
    for name, content in (
        ("src/oidc.ts", OIDC_TS),
        ("src/main.tsx", MAIN_TSX),
        ("src/App.tsx", APP_TSX),
    ):
        path = os.path.join(FRONTEND, name)
        with open(path, "w") as fh:
            fh.write(content)
        print(f"oracle: wrote {path}")

    npm = shutil.which("npm") or "/opt/node/bin/npm"
    result = subprocess.run(
        [npm, "run", "build"], cwd=FRONTEND, capture_output=True, text=True
    )
    if result.returncode != 0:
        print(result.stdout[-4000:])
        print(result.stderr[-4000:], file=sys.stderr)
        sys.exit("oracle: npm run build failed")
    print("oracle: npm run build ok")


def main():
    token = admin_token()
    fix_client(token)
    wire_app()
    print("oracle: done")


if __name__ == "__main__":
    main()
