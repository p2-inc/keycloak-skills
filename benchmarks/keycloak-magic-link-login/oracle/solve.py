#!/usr/bin/env python3
"""Human-written oracle: turns on passwordless magic-link login for the acme realm.

Three pieces, all through the Admin REST API:

  1. Realm SMTP settings. Unconfigured by default; without them the
     authenticator's email send silently fails and no link ever goes out.

  2. The "ext-magic-form" execution's own config, set to
     ext-magic-create-nonexistent-user=false. Its factory default is true,
     which - because the login response is identical either way, by design,
     to avoid revealing which addresses are registered - silently provisions
     a new account for any email a visitor types. Nothing about the response
     to that visitor changes; only the realm's user list does.

  3. Binding the realm's browserFlow to "magic link" - a flow Keycloak already
     created automatically the moment the provider was present, so no flow
     authoring is needed, only binding it.

Finishes by driving the login itself the way the verifier does: a known
address should get mail and a completed login; an unregistered one should get
neither mail nor a new account, despite an identical response on the page.
"""

import glob
import json
import pathlib
import re
import sys
import time
import urllib.parse

import requests

CREDS_PATH = "/root/admin_credentials.txt"
FLOW_ALIAS = "magic link"
CAPTURE_DIR = "/var/mail-capture"
KNOWN_EMAIL = "priya@acme.example"
UNKNOWN_EMAIL = "oracle-ghost@acme.example"
TIMEOUT = 30


def load_settings(path):
    values = {}
    for line in pathlib.Path(path).read_text().splitlines():
        line = line.strip()
        if not line or "=" not in line or line.startswith("#"):
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def get_admin_token(base_url, admin_realm, username, password):
    resp = requests.post(
        f"{base_url}/realms/{admin_realm}/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": username,
            "password": password,
        },
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def configure_smtp(base_url, headers, realm):
    """Point outgoing mail at the local capture server.

    A realm ships with no SMTP settings at all; the authenticator's send call
    raises EmailException and is caught internally, so a missing configuration
    fails silently rather than with an error the agent would see.
    """
    current = requests.get(f"{base_url}/admin/realms/{realm}", headers=headers, timeout=TIMEOUT)
    current.raise_for_status()
    representation = current.json()
    representation["smtpServer"] = {
        "host": "localhost",
        "port": "1025",
        "from": "noreply@acme.example",
        "auth": "false",
        "ssl": "false",
        "starttls": "false",
    }
    resp = requests.put(
        f"{base_url}/admin/realms/{realm}", headers=headers, json=representation, timeout=TIMEOUT
    )
    resp.raise_for_status()


def find_magic_link_execution(base_url, headers, realm):
    resp = requests.get(
        f"{base_url}/admin/realms/{realm}/authentication/flows/"
        f"{urllib.parse.quote(FLOW_ALIAS)}/executions",
        headers=headers,
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    executions = resp.json()
    matches = [e for e in executions if e.get("providerId") == "ext-magic-form"]
    if len(matches) != 1:
        raise RuntimeError(f"expected one ext-magic-form execution, found {len(matches)}")
    return matches[0]


def require_existing_accounts_only(base_url, headers, realm, execution):
    """Attach config that stops the authenticator creating accounts on the fly.

    The factory default (true) means any email a visitor types gets an account
    if none exists - silent, since the page response doesn't change either way.
    """
    resp = requests.post(
        f"{base_url}/admin/realms/{realm}/authentication/executions/{execution['id']}/config",
        headers=headers,
        json={
            "alias": "magic-link-existing-accounts-only",
            "config": {"ext-magic-create-nonexistent-user": "false"},
        },
        timeout=TIMEOUT,
    )
    resp.raise_for_status()


def bind_flow(base_url, headers, realm):
    current = requests.get(f"{base_url}/admin/realms/{realm}", headers=headers, timeout=TIMEOUT)
    current.raise_for_status()
    representation = current.json()
    representation["browserFlow"] = FLOW_ALIAS
    resp = requests.put(
        f"{base_url}/admin/realms/{realm}", headers=headers, json=representation, timeout=TIMEOUT
    )
    resp.raise_for_status()


# --- driving the login, headlessly -----------------------------------------


def _relax_cookies(session):
    for cookie in session.cookies:
        cookie.secure = False


def _form_action(html):
    match = re.search(r'<form[^>]*action="([^"]+)"', html or "", re.I)
    if not match:
        raise RuntimeError("no form on the page")
    return match.group(1).replace("&amp;", "&")


def _authorization_url(base_url, realm, client_id, redirect_uri, state):
    return f"{base_url}/realms/{realm}/protocol/openid-connect/auth?" + urllib.parse.urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "scope": "openid email",
            "redirect_uri": redirect_uri,
            "state": state,
            "nonce": f"nonce-{state}",
        }
    )


def _submit_email(base_url, realm, client_id, redirect_uri, email, state):
    session = requests.Session()
    page = session.get(
        _authorization_url(base_url, realm, client_id, redirect_uri, state), timeout=TIMEOUT
    )
    _relax_cookies(session)
    resp = session.post(
        _form_action(page.text), data={"username": email}, timeout=TIMEOUT, allow_redirects=False
    )
    _relax_cookies(session)
    return session, resp


def _latest_capture_for(email, since):
    marker = email.replace("@", "-at-")
    matches = sorted(pathlib.Path(CAPTURE_DIR).glob(f"*{marker}*.json"))
    for path in reversed(matches):
        record = json.loads(path.read_text())
        if record["received_at"] >= since:
            return record
    return None


def _follow_to_redirect_uri(session, location, redirect_uri, limit=8):
    for _ in range(limit):
        if not location or location.startswith(redirect_uri):
            return location
        target = location if location.startswith("http") else f"http://localhost:8080{location}"
        hop = session.get(target, timeout=TIMEOUT, allow_redirects=False)
        _relax_cookies(session)
        location = hop.headers.get("Location", "")
    return location


def _user_exists(base_url, headers, realm, username_or_email):
    resp = requests.get(
        f"{base_url}/admin/realms/{realm}/users",
        headers=headers,
        params={"search": username_or_email},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return len(resp.json()) > 0


def self_check(base_url, headers, realm, client_id, redirect_uri):
    # --- known address: mail out, link works, code returned ---
    since = time.time()
    state = "oracle-known"
    session, resp = _submit_email(base_url, realm, client_id, redirect_uri, KNOWN_EMAIL, state)
    if resp.status_code != 200:
        raise RuntimeError(f"submitting {KNOWN_EMAIL} failed: {resp.status_code}")

    record = None
    for _ in range(10):
        record = _latest_capture_for(KNOWN_EMAIL, since)
        if record:
            break
        time.sleep(0.5)
    if record is None:
        raise RuntimeError(f"no mail captured for {KNOWN_EMAIL}; SMTP is likely misconfigured")

    body = record.get("body_plain") or record.get("body_html") or ""
    link_match = re.search(r"(http://\S*action-token\S*)", body)
    if not link_match:
        raise RuntimeError(f"no action-token link found in captured mail: {body[:200]}")
    link = link_match.group(1).rstrip(".,)")

    opened = session.get(link, timeout=TIMEOUT, allow_redirects=False)
    _relax_cookies(session)
    final = _follow_to_redirect_uri(session, opened.headers.get("Location", ""), redirect_uri)
    if not final or not final.startswith(redirect_uri):
        raise RuntimeError(f"the magic link never returned to {redirect_uri}: {final!r}")
    query = urllib.parse.parse_qs(urllib.parse.urlparse(final).query)
    if "code" not in query:
        raise RuntimeError(f"no authorization code returned: {final[:200]}")
    if query.get("state") != [state]:
        raise RuntimeError(f"state was not preserved: {query.get('state')}")

    # --- unregistered address: identical response, but no mail, no account ---
    since2 = time.time()
    _, resp2 = _submit_email(base_url, realm, client_id, redirect_uri, UNKNOWN_EMAIL, "oracle-unknown")
    if resp2.status_code != resp.status_code:
        raise RuntimeError(
            f"unregistered address got a different response ({resp2.status_code}) "
            f"than a registered one ({resp.status_code}); this leaks which emails are registered"
        )
    time.sleep(1.5)
    if _latest_capture_for(UNKNOWN_EMAIL, since2) is not None:
        raise RuntimeError(f"mail was sent for the unregistered address {UNKNOWN_EMAIL}")
    if _user_exists(base_url, headers, realm, UNKNOWN_EMAIL):
        raise RuntimeError(f"a new account was created for {UNKNOWN_EMAIL}")

    print(
        "oracle self-check passed: known address received mail and completed login, "
        "unregistered address got the same page response with no mail and no new account"
    )


def main():
    creds = load_settings(CREDS_PATH)
    base_url = creds["keycloak_base_url"].rstrip("/")
    realm = creds["target_realm"]
    client_id = creds["app_client_id"]
    redirect_uri = creds["app_redirect_uri"]

    admin_token = get_admin_token(
        base_url, creds["admin_realm"], creds["admin_username"], creds["admin_password"]
    )
    headers = {"Authorization": f"Bearer {admin_token}"}

    configure_smtp(base_url, headers, realm)
    execution = find_magic_link_execution(base_url, headers, realm)
    require_existing_accounts_only(base_url, headers, realm, execution)
    bind_flow(base_url, headers, realm)

    self_check(base_url, headers, realm, client_id, redirect_uri)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - surface any failure to the caller
        detail = ""
        if isinstance(exc, requests.HTTPError) and exc.response is not None:
            detail = f" body={exc.response.text[:400]}"
        print(f"oracle failed: {exc}{detail}", file=sys.stderr)
        sys.exit(1)
