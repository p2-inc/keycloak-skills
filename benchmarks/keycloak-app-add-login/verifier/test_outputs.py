"""Verifier for keycloak-app-add-login.

Asserts the distinguishing properties, not the happy path:

  * The client was UPDATED, not replaced - the acme-department protocol mapper the
    fixture ships must still be there. A delete-and-re-create, or a hand-built PUT
    body, destroys it while still producing a working login.
  * The browser-side token request is allowed by CORS. Registering the redirect URI
    alone yields a client that passes every server-side login and fails only in a
    real browser. The token exchange returns 200 either way, so the
    Access-Control-Allow-Origin header is the only thing that separates a correct
    solution from one that merely looks correct.
"""

import base64
import hashlib
import os
import re
import secrets
import shutil
import subprocess
import urllib.parse

import pytest
import requests

# The verifier runs under a shell that does not inherit the image's ENV PATH, so
# `npm` is not resolvable by name here even though it is on PATH for the agent.
# Resolve it explicitly rather than letting subprocess raise FileNotFoundError.
NPM = shutil.which("npm") or "/opt/node/bin/npm"
# npm's shim is `#!/usr/bin/env node`, so node must be resolvable too.
BUILD_ENV = {**os.environ, "PATH": "/opt/node/bin:" + os.environ.get("PATH", "/usr/bin:/bin")}

BASE = "http://localhost:8080/auth"
REALM = "acme"
CLIENT_ID = "acme-portal"
APP_ORIGIN = "http://localhost:5173"
APP_REDIRECT = "http://localhost:5173/"
FRONTEND = "/app/frontend"
FIXTURE_MAPPER = "acme-department"
LOGIN_USER = "portal-user"
LOGIN_PASSWORD = "portal-pass-1"
TIMEOUT = 30


# ---------------------------------------------------------------- helpers


def admin_token():
    creds = {}
    with open("/root/admin_credentials.txt") as fh:
        for line in fh:
            if ":" in line:
                k, _, v = line.partition(":")
                creds[k.strip().lower()] = v.strip()
    resp = requests.post(
        f"{BASE}/realms/master/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": creds.get("username") or creds.get("user") or "admin",
            "password": creds.get("password") or "admin_change_me",
        },
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


@pytest.fixture(scope="session")
def client_repr():
    token = admin_token()
    resp = requests.get(
        f"{BASE}/admin/realms/{REALM}/clients",
        params={"clientId": CLIENT_ID},
        headers={"Authorization": f"Bearer {token}"},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    found = resp.json()
    assert found, f"client {CLIENT_ID} no longer exists in realm {REALM}"
    uuid = found[0]["id"]
    full = requests.get(
        f"{BASE}/admin/realms/{REALM}/clients/{uuid}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=TIMEOUT,
    )
    full.raise_for_status()
    return full.json()


def relax_cookies(session):
    """Keycloak's auth cookies are Secure. Browsers send them over http://localhost
    (loopback is a secure context); requests does not, and every POST then fails a
    session check. Clear the flag after each response."""
    for cookie in session.cookies:
        cookie.secure = False


def pkce_pair():
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).decode().rstrip("=")
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )
    return verifier, challenge


@pytest.fixture(scope="session")
def authorization_code():
    """Drive a real browser login and return (code, code_verifier).

    Deliberately a full auth-code + PKCE round trip rather than a direct grant:
    a direct grant would pass even if redirect URIs were never registered.
    """
    verifier, challenge = pkce_pair()
    session = requests.Session()

    authorize = f"{BASE}/realms/{REALM}/protocol/openid-connect/auth?" + urllib.parse.urlencode(
        {
            "client_id": CLIENT_ID,
            "redirect_uri": APP_REDIRECT,
            "response_type": "code",
            "scope": "openid profile email",
            "state": secrets.token_urlsafe(16),
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    page = session.get(authorize, timeout=TIMEOUT, allow_redirects=True)
    relax_cookies(session)
    assert page.status_code == 200, (
        f"authorization endpoint returned {page.status_code}. If this is a redirect "
        f"to an error page, the redirect_uri {APP_REDIRECT!r} is not registered on "
        f"{CLIENT_ID}."
    )
    assert "Invalid parameter: redirect_uri" not in page.text, (
        f"Keycloak rejected redirect_uri {APP_REDIRECT!r} - it is not registered on "
        f"{CLIENT_ID}. Note the trailing slash: oidc-spa returns to the app's base URL."
    )

    action = re.search(r'<form[^>]*action="([^"]+)"', page.text, re.I)
    assert action, "no login form on the authorization page"
    action_url = action.group(1).replace("&amp;", "&")
    if not action_url.startswith("http"):
        action_url = "/".join(BASE.split("/")[:3]) + action_url

    posted = session.post(
        action_url,
        data={"username": LOGIN_USER, "password": LOGIN_PASSWORD},
        timeout=TIMEOUT,
        allow_redirects=False,
    )
    relax_cookies(session)

    # Follow redirects by hand: the final hop points at the app's own origin, where
    # nothing is listening, and requests would raise ConnectionError on it.
    location = posted.headers.get("Location", "")
    hops = 0
    while posted.status_code in (301, 302, 303, 307, 308) and hops < 5:
        if location.startswith(APP_ORIGIN):
            break
        posted = session.get(location, timeout=TIMEOUT, allow_redirects=False)
        relax_cookies(session)
        location = posted.headers.get("Location", "")
        hops += 1

    assert location.startswith(APP_ORIGIN), (
        f"login did not return to the app. Last Location was {location!r}. "
        f"Expected a redirect to {APP_ORIGIN}."
    )
    query = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)
    assert "code" in query, f"no authorization code in the callback: {location!r}"
    return query["code"][0], verifier


# ---------------------------------------------------------------- assertions


def test_app_builds():
    """`npm run build` still exits 0."""
    assert os.path.exists(NPM), f"npm not found at {NPM} - verifier environment problem"
    result = subprocess.run(
        [NPM, "run", "build"],
        cwd=FRONTEND,
        capture_output=True,
        text=True,
        timeout=420,
        env=BUILD_ENV,
    )
    assert result.returncode == 0, (
        "npm run build failed:\n"
        f"stdout:\n{result.stdout[-3000:]}\n\nstderr:\n{result.stderr[-3000:]}"
    )


def test_app_source_wires_authentication():
    """The React app actually contains login wiring - not just a repaired client."""
    sources = []
    for root, _dirs, files in os.walk(os.path.join(FRONTEND, "src")):
        for name in files:
            if name.endswith((".ts", ".tsx", ".js", ".jsx")):
                with open(os.path.join(root, name)) as fh:
                    sources.append(fh.read())
    blob = "\n".join(sources)
    assert blob.strip(), "no source files under /app/frontend/src"

    assert re.search(r"oidc-spa|keycloak-js|oidc-client-ts", blob), (
        "no OIDC library imported anywhere in src/. The app still has no "
        "authentication code."
    )
    assert re.search(r"\blogin\b|\bsignIn\b|\bloginRedirect\b", blob, re.I), (
        "no login entry point found in src/"
    )
    assert re.search(r"\blogout\b|\bsignOut\b", blob, re.I), (
        "no logout entry point found in src/"
    )


def test_client_is_public_with_standard_flow(client_repr):
    assert client_repr.get("publicClient") is True, (
        "acme-portal must stay a public client - a browser bundle cannot hold a secret"
    )
    assert client_repr.get("standardFlowEnabled") is True, (
        "standard (authorization code) flow must be enabled"
    )
    assert client_repr.get("enabled") is True, "acme-portal is disabled"


def test_pkce_is_required(client_repr):
    method = (client_repr.get("attributes") or {}).get("pkce.code.challenge.method")
    assert method == "S256", (
        f"PKCE challenge method is {method!r}, expected 'S256'. A public client "
        f"without PKCE is vulnerable to authorization-code interception."
    )


def test_redirect_uri_registered_for_dev_server(client_repr):
    uris = client_repr.get("redirectUris") or []
    assert APP_REDIRECT in uris, (
        f"{APP_REDIRECT!r} is not registered. Registered: {uris}. Note the trailing "
        f"slash - oidc-spa redirects back to the app's base URL, and Keycloak matches "
        f"redirect URIs exactly."
    )


def test_existing_client_configuration_survived(client_repr):
    """The fixture's protocol mapper must still be there.

    This is what separates an update from a delete-and-re-create, and from a
    hand-built PUT body: Keycloak's client PUT replaces the whole representation,
    so anything omitted is destroyed silently, with a 204 that looks like success.
    """
    mappers = [m.get("name") for m in client_repr.get("protocolMappers") or []]
    assert FIXTURE_MAPPER in mappers, (
        f"the {FIXTURE_MAPPER!r} protocol mapper is gone. Present: {mappers}. "
        f"The client was replaced rather than updated - read the current "
        f"representation, merge, then PUT it back."
    )


def test_full_pkce_login_round_trip(authorization_code):
    """A real browser login reaches the app's redirect URI with a code."""
    code, _verifier = authorization_code
    assert code, "no authorization code returned"


def test_token_endpoint_allows_the_browser_origin(authorization_code):
    """THE distinguishing assertion.

    Exchanges the code the way the browser does - with an Origin header. Keycloak
    returns 200 whether or not the origin is allowed; only the CORS response header
    differs, and only a real browser would notice. A verifier that skipped this
    would score a client with empty webOrigins as fully correct.
    """
    code, verifier = authorization_code
    resp = requests.post(
        f"{BASE}/realms/{REALM}/protocol/openid-connect/token",
        data={
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "code": code,
            "redirect_uri": APP_REDIRECT,
            "code_verifier": verifier,
        },
        headers={"Origin": APP_ORIGIN},
        timeout=TIMEOUT,
    )
    assert resp.status_code == 200, (
        f"token exchange failed: {resp.status_code} {resp.text[:500]}"
    )
    payload = resp.json()
    assert "access_token" in payload and "id_token" in payload, (
        f"token response missing tokens: {sorted(payload)}"
    )

    allow_origin = resp.headers.get("Access-Control-Allow-Origin")
    assert allow_origin in (APP_ORIGIN, "*"), (
        f"the token endpoint did not allow origin {APP_ORIGIN!r} "
        f"(Access-Control-Allow-Origin: {allow_origin!r}).\n\n"
        f"The login itself works - this exchange returned 200 - but a real browser "
        f"blocks this response, so the app never receives its tokens. Redirect URIs "
        f"and web origins are separate settings: registering the redirect URI does "
        f"not authorize the CORS origin. Add {APP_ORIGIN!r} to the client's "
        f"webOrigins (or '+')."
    )
