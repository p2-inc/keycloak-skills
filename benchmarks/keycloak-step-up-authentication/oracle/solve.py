#!/usr/bin/env python3

# Copyright 2026 Phase Two, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Human-written oracle: ACR -> LoA step-up authentication, two trust levels in one session.

  step-up-flow (top level)                        ALTERNATIVE level
    auth-cookie                                      ALTERNATIVE  priority 0
    identity-provider-redirector                     ALTERNATIVE  priority 10
    Step-up forms                                     ALTERNATIVE  priority 20
      Levels                                           REQUIRED    priority 0
        Level 1                                          CONDITIONAL priority 0  (first!)
          conditional-level-of-authentication              REQUIRED (loa-condition-level=1, loa-max-age=36000)
          auth-username-password-form                      REQUIRED
        Level 2                                          CONDITIONAL priority 10 (second!)
          conditional-level-of-authentication              REQUIRED (loa-condition-level=2, loa-max-age=300)
          auth-otp-form                                    REQUIRED

Level 1 must be listed before Level 2 inside "Levels" - a brand new session has reached no
level yet, so the first level sub-flow in the list always runs on a plain first login. If
Level 2 were listed first, every first login would be asked for the OTP code regardless of
what was requested.

Realm attribute acr.loa.map = {"silver": 1, "gold": 2} maps the ACR values the application
asks for onto those levels. acme-payments gets client attribute minimum.acr.value=gold so it
is forced to the strong check even when nothing is requested - deliberately NOT
default.acr.values, which is only a default the browser can override.

Then this file drives every one of task.md's requirements over plain HTTP exactly the way the
verifier will, including the two documented wrong-solution traps: ordering level 2 before
level 1 (checked implicitly - a plain first login must not see the OTP form), and using
default.acr.values instead of minimum.acr.value (checked explicitly - a request that asks for
silver on acme-payments must still be forced to gold).

priya's authenticator is mocked: her OTP credential is seeded in the realm fixture with a
known secret, so her codes are computed here. morgan is not touched - he has no second
factor and isn't exercised by this flow.
"""

import hashlib
import hmac
import base64
import html as htmllib
import json
import pathlib
import re
import struct
import sys
import time
import urllib.parse

import requests

CREDS_PATH = "/root/admin_credentials.txt"
TIMEOUT = 30

FLOW_ALIAS = "step-up-flow"
FORMS_ALIAS = "Step-up forms"
LEVELS_ALIAS = "Levels"
LVL1_ALIAS = "Level 1"
LVL2_ALIAS = "Level 2"

PRIYA, PRIYA_PASSWORD, PRIYA_TOTP_SECRET = "priya", "Priya!Pass1", "AcmePriyaTotp2026Sec"
MORGAN, MORGAN_PASSWORD = "morgan", "Morgan!Pass1"

PASSWORD_FORM, OTP_FORM = "kc-form-login", "kc-otp-login-form"

PAYMENTS_CLIENT_ID = "acme-payments"
PAYMENTS_REDIRECT_URI = "http://localhost:9998/callback"


def load_settings(path):
    values = {}
    for line in pathlib.Path(path).read_text().splitlines():
        line = line.strip()
        if line and "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def q(alias):
    return urllib.parse.quote(alias, safe="")


def get_admin_token(base, admin_realm, username, password):
    resp = requests.post(f"{base}/realms/{admin_realm}/protocol/openid-connect/token",
                         data={"grant_type": "password", "client_id": "admin-cli",
                               "username": username, "password": password}, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()["access_token"]


# --------------------------------------------------------------- configuration


def executions(base, realm, token, alias):
    resp = requests.get(f"{base}/admin/realms/{realm}/authentication/flows/{q(alias)}/executions",
                        headers=auth(token), timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def create_top_flow(base, realm, token):
    resp = requests.post(f"{base}/admin/realms/{realm}/authentication/flows", headers=auth(token),
                         json={"alias": FLOW_ALIAS, "providerId": "basic-flow", "topLevel": True,
                               "builtIn": False}, timeout=TIMEOUT)
    if resp.status_code not in (201, 409):
        resp.raise_for_status()


def add_execution(base, realm, token, flow_alias, provider, priority):
    existing = {e.get("providerId") for e in executions(base, realm, token, flow_alias)}
    if provider in existing:
        return
    resp = requests.post(
        f"{base}/admin/realms/{realm}/authentication/flows/{q(flow_alias)}/executions/execution",
        headers=auth(token), json={"provider": provider, "priority": priority}, timeout=TIMEOUT)
    if resp.status_code not in (201, 204):
        raise RuntimeError(
            f"failed to add execution {provider!r} to flow {flow_alias!r}: "
            f"{resp.status_code} {resp.text[:300]}")
    # Keycloak's admin REST can briefly lag between a successful POST and the next GET
    # reflecting it; retry the read-back a few times before treating it as a real failure.
    after = set()
    rows = []
    for _ in range(5):
        rows = executions(base, realm, token, flow_alias)
        after = {e.get("providerId") for e in rows}
        if provider in after:
            break
        time.sleep(0.5)
    if provider not in after:
        raise RuntimeError(
            f"POST to add execution {provider!r} under flow {flow_alias!r} returned "
            f"{resp.status_code} but the execution did not appear in a read-back "
            f"(rows now: {rows!r})")


def add_subflow(base, realm, token, parent_alias, child_alias, priority):
    existing = {e.get("displayName") for e in executions(base, realm, token, parent_alias)}
    if child_alias in existing:
        return
    resp = requests.post(
        f"{base}/admin/realms/{realm}/authentication/flows/{q(parent_alias)}/executions/flow",
        headers=auth(token),
        json={"alias": child_alias, "provider": "basic-flow", "type": "basic-flow",
              "priority": priority}, timeout=TIMEOUT)
    if resp.status_code not in (201, 204):
        raise RuntimeError(
            f"failed to add sub-flow {child_alias!r} under {parent_alias!r}: "
            f"{resp.status_code} {resp.text[:300]}")
    after = {e.get("displayName") for e in executions(base, realm, token, parent_alias)}
    if child_alias not in after:
        raise RuntimeError(
            f"POST to add sub-flow {child_alias!r} under {parent_alias!r} returned "
            f"{resp.status_code} but the sub-flow did not appear in a read-back "
            f"(rows now: {executions(base, realm, token, parent_alias)!r})")


def set_requirement(base, realm, token, flow_alias, key, requirement):
    rows = []
    for _ in range(5):
        rows = executions(base, realm, token, flow_alias)
        row_keys = {(row.get("providerId") or row.get("displayName")) for row in rows}
        if key in row_keys:
            break
        time.sleep(0.5)
    for row in rows:
        row_key = row.get("providerId") or row.get("displayName")
        if row_key == key:
            if row.get("requirement") == requirement:
                return
            row = dict(row)
            row["requirement"] = requirement
            requests.put(f"{base}/admin/realms/{realm}/authentication/flows/{q(flow_alias)}/executions",
                        headers=auth(token), json=row, timeout=TIMEOUT).raise_for_status()
            return
    raise RuntimeError(
        f"no execution matching {key!r} found under flow {flow_alias!r} "
        f"(rows: {rows!r})")


def attach_loa_config(base, realm, token, sub_flow_alias, level, max_age, config_alias):
    rows = executions(base, realm, token, sub_flow_alias)
    cond = next((r for r in rows if r.get("providerId") == "conditional-level-of-authentication"), None)
    if cond is None:
        raise RuntimeError(f"no conditional-level-of-authentication execution under {sub_flow_alias!r}")
    if cond.get("authenticationConfig"):
        # Already configured (idempotent re-run): verify, don't double-attach.
        return
    resp = requests.post(f"{base}/admin/realms/{realm}/authentication/executions/{cond['id']}/config",
                         headers=auth(token),
                         json={"alias": config_alias,
                               "config": {"loa-condition-level": str(level), "loa-max-age": str(max_age)}},
                         timeout=TIMEOUT)
    resp.raise_for_status()


def build_flow(base, realm, token):
    create_top_flow(base, realm, token)

    add_execution(base, realm, token, FLOW_ALIAS, "auth-cookie", 0)
    add_execution(base, realm, token, FLOW_ALIAS, "identity-provider-redirector", 10)
    add_subflow(base, realm, token, FLOW_ALIAS, FORMS_ALIAS, 20)

    add_subflow(base, realm, token, FORMS_ALIAS, LEVELS_ALIAS, 0)

    # Level 1 THEN Level 2 - order is load-bearing (see module docstring).
    add_subflow(base, realm, token, LEVELS_ALIAS, LVL1_ALIAS, 0)
    add_subflow(base, realm, token, LEVELS_ALIAS, LVL2_ALIAS, 10)

    add_execution(base, realm, token, LVL1_ALIAS, "conditional-level-of-authentication", 0)
    add_execution(base, realm, token, LVL1_ALIAS, "auth-username-password-form", 10)

    add_execution(base, realm, token, LVL2_ALIAS, "conditional-level-of-authentication", 0)
    add_execution(base, realm, token, LVL2_ALIAS, "auth-otp-form", 10)

    set_requirement(base, realm, token, FLOW_ALIAS, "auth-cookie", "ALTERNATIVE")
    set_requirement(base, realm, token, FLOW_ALIAS, "identity-provider-redirector", "ALTERNATIVE")
    set_requirement(base, realm, token, FLOW_ALIAS, FORMS_ALIAS, "ALTERNATIVE")
    set_requirement(base, realm, token, FORMS_ALIAS, LEVELS_ALIAS, "REQUIRED")
    set_requirement(base, realm, token, LEVELS_ALIAS, LVL1_ALIAS, "CONDITIONAL")
    set_requirement(base, realm, token, LEVELS_ALIAS, LVL2_ALIAS, "CONDITIONAL")
    set_requirement(base, realm, token, LVL1_ALIAS, "conditional-level-of-authentication", "REQUIRED")
    set_requirement(base, realm, token, LVL1_ALIAS, "auth-username-password-form", "REQUIRED")
    set_requirement(base, realm, token, LVL2_ALIAS, "conditional-level-of-authentication", "REQUIRED")
    set_requirement(base, realm, token, LVL2_ALIAS, "auth-otp-form", "REQUIRED")

    attach_loa_config(base, realm, token, LVL1_ALIAS, 1, 36000, "loa-level-1")
    attach_loa_config(base, realm, token, LVL2_ALIAS, 2, 300, "loa-level-2")

    flows = requests.get(f"{base}/admin/realms/{realm}/authentication/flows", headers=auth(token),
                         timeout=TIMEOUT).json()
    return next(f["id"] for f in flows if f["alias"] == FLOW_ALIAS)


def set_acr_loa_map_and_token_lifespan(base, realm, token):
    rep = requests.get(f"{base}/admin/realms/{realm}", headers=auth(token), timeout=TIMEOUT).json()
    attributes = rep.get("attributes") or {}
    attributes["acr.loa.map"] = json.dumps({"silver": 1, "gold": 2})
    rep["attributes"] = attributes
    rep["accessTokenLifespan"] = 300
    requests.put(f"{base}/admin/realms/{realm}", headers=auth(token), json=rep,
                 timeout=TIMEOUT).raise_for_status()


def bind_realm_flow(base, realm, token, flow_alias):
    rep = requests.get(f"{base}/admin/realms/{realm}", headers=auth(token), timeout=TIMEOUT).json()
    rep["browserFlow"] = flow_alias
    requests.put(f"{base}/admin/realms/{realm}", headers=auth(token), json=rep,
                 timeout=TIMEOUT).raise_for_status()


def pin_client_to_gold(base, realm, token, client_id):
    clients = requests.get(f"{base}/admin/realms/{realm}/clients",
                           params={"clientId": client_id}, headers=auth(token),
                           timeout=TIMEOUT).json()
    client = clients[0]
    attributes = client.get("attributes") or {}
    attributes["minimum.acr.value"] = "gold"
    client["attributes"] = attributes
    requests.put(f"{base}/admin/realms/{realm}/clients/{client['id']}", headers=auth(token),
                json=client, timeout=TIMEOUT).raise_for_status()


def ensure_acr_mapper_present(base, realm, token):
    scopes = requests.get(f"{base}/admin/realms/{realm}/client-scopes", headers=auth(token),
                          timeout=TIMEOUT).json()
    acr_scope = next((s for s in scopes if s.get("name") == "acr"), None)
    if acr_scope is None:
        raise RuntimeError("realm's default 'acr' client scope not found")
    mappers = requests.get(
        f"{base}/admin/realms/{realm}/client-scopes/{acr_scope['id']}/protocol-mappers/models",
        headers=auth(token), timeout=TIMEOUT).json()
    has_acr_mapper = any(m.get("protocolMapper") == "oidc-acr-mapper" for m in mappers)
    if not has_acr_mapper:
        raise RuntimeError("realm's 'acr' client scope has no oidc-acr-mapper configured")


# ---------------------------------------------------------------- TOTP + JWT helpers


def totp(secret, at=None, digits=6, period=30):
    counter = int((time.time() if at is None else at) // period)
    mac = hmac.new(secret.encode("utf-8"), struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    return str((struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7FFFFFFF)
               % (10 ** digits)).zfill(digits)


def fresh_code(secret, period=30):
    time.sleep(period - (time.time() % period) + 1)
    return totp(secret, period=period)


def wrong_code(secret):
    now = time.time()
    taken = {totp(secret, at=now + d * 30) for d in (-2, -1, 0, 1, 2)}
    return next(c for c in ("000000", "111111", "123456", "999999") if c not in taken)


def _b64url_decode(segment):
    padded = segment + "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def decode_jwt_payload(token):
    parts = token.split(".")
    if len(parts) != 3:
        raise RuntimeError(f"not a JWT: {token[:80]!r}")
    return json.loads(_b64url_decode(parts[1]))


# ---------------------------------------------------------------- HTTP driving helpers


def relax(session):
    for cookie in session.cookies:
        cookie.secure = False


def form_tag(html, form_id):
    for match in re.finditer(r"<form\b[^>]*>", html or "", re.I):
        if f'id="{form_id}"' in match.group(0):
            return match.group(0)
    return None


def form_action(html, form_id):
    tag = form_tag(html, form_id)
    action = re.search(r'action="([^"]+)"', tag or "")
    return htmllib.unescape(action.group(1)) if action else None


def hidden_value(html, name):
    tag = re.search(rf'<input\b[^>]*name="{re.escape(name)}"[^>]*>', html or "", re.I)
    value = re.search(r'value="([^"]*)"', tag.group(0)) if tag else None
    return htmllib.unescape(value.group(1)) if value else None


def describe(html):
    page_id = re.search(r'data-page-id="([^"]+)"', html or "")
    forms = re.findall(r'<form\b[^>]*\bid="([^"]+)"', html or "")
    form = re.search(r"<form\b.*?</form>", html or "", re.I | re.S)
    return (f"page_id={page_id.group(1) if page_id else None!r}, forms={forms}, "
            f"form={(form.group(0) if form else (html or '')[:400])[:1500]!r}")


def follow(session, resp, redirect_uri):
    for _ in range(10):
        relax(session)
        if resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("Location", "")
            if location.startswith(redirect_uri):
                return "callback", location
            resp = session.get(urllib.parse.urljoin(resp.url, location), timeout=TIMEOUT,
                               allow_redirects=False)
            continue
        return "page", resp.text
    return "page", resp.text


def auth_url(base, realm, state, client_id, redirect_uri, acr_values=None, claims=None):
    params = {"client_id": client_id, "response_type": "code", "scope": "openid",
              "redirect_uri": redirect_uri, "state": state}
    if acr_values:
        params["acr_values"] = acr_values
    if claims:
        params["claims"] = json.dumps(claims)
    return f"{base}/realms/{realm}/protocol/openid-connect/auth?" + urllib.parse.urlencode(params)


def start(base, realm, state, client_id, redirect_uri, acr_values=None, claims=None, session=None):
    session = session or requests.Session()
    url = auth_url(base, realm, state, client_id, redirect_uri, acr_values=acr_values, claims=claims)
    resp = session.get(url, timeout=TIMEOUT, allow_redirects=False)
    kind, value = follow(session, resp, redirect_uri)
    return session, kind, value


def submit_password(session, html, username, password, redirect_uri):
    resp = session.post(form_action(html, PASSWORD_FORM),
                        data={"username": username, "password": password},
                        timeout=TIMEOUT, allow_redirects=False)
    return follow(session, resp, redirect_uri)


def submit_otp(session, html, code, redirect_uri):
    data = {"otp": code}
    selected = hidden_value(html, "selectedCredentialId")
    if selected:
        data["selectedCredentialId"] = selected
    resp = session.post(form_action(html, OTP_FORM), data=data, timeout=TIMEOUT,
                        allow_redirects=False)
    return follow(session, resp, redirect_uri)


def assert_callback_with_code(kind, value, state, what):
    if kind != "callback":
        raise RuntimeError(f"{what} did not reach a callback: {describe(value)}")
    query = urllib.parse.parse_qs(urllib.parse.urlparse(value).query)
    if "error" in query:
        raise RuntimeError(f"{what}: callback carried an error: {value[:300]}")
    if "code" not in query:
        raise RuntimeError(f"{what}: no authorization code returned: {value[:250]}")
    if query.get("state") != [state]:
        raise RuntimeError(f"{what}: state not preserved: sent {state!r} got {query.get('state')!r}")
    return query["code"][0]


def exchange_code(base, realm, code, client_id, redirect_uri):
    resp = requests.post(f"{base}/realms/{realm}/protocol/openid-connect/token",
                         data={"grant_type": "authorization_code", "code": code,
                               "client_id": client_id, "redirect_uri": redirect_uri},
                         timeout=TIMEOUT)
    if resp.status_code != 200:
        raise RuntimeError(f"token exchange failed ({resp.status_code}): {resp.text[:400]}")
    return resp.json()


# ---------------------------------------------------------------- self-check (every requirement)


def self_check(base, realm, client_id, redirect_uri):
    # 1. no acr requested -> password only -> acr=silver
    state = "oracle-1-no-acr"
    session, kind, value = start(base, realm, state, client_id, redirect_uri)
    if kind != "page" or not form_tag(value, PASSWORD_FORM):
        raise RuntimeError(f"1: expected password form with no acr requested: {describe(value)}")
    kind, value = submit_password(session, value, PRIYA, PRIYA_PASSWORD, redirect_uri)
    if kind != "callback":
        raise RuntimeError(f"1: expected immediate login with no acr requested: {describe(value)}")
    code = assert_callback_with_code(kind, value, state, "1: plain login")
    tokens = exchange_code(base, realm, code, client_id, redirect_uri)
    acr = decode_jwt_payload(tokens["id_token"]).get("acr")
    if acr != "silver":
        raise RuntimeError(f"1: expected acr=silver, got {acr!r}")
    print("  1: no acr requested -> password only -> acr=silver")

    # 2. same session, request gold -> only code form -> acr=gold
    state2 = "oracle-2-step-up"
    url = auth_url(base, realm, state2, client_id, redirect_uri,
                   claims={"id_token": {"acr": {"essential": True, "values": ["gold"]}}})
    resp = session.get(url, timeout=TIMEOUT, allow_redirects=False)
    relax(session)
    kind, value = follow(session, resp, redirect_uri)
    if kind != "page" or form_tag(value, PASSWORD_FORM) or not form_tag(value, OTP_FORM):
        raise RuntimeError(f"2: expected ONLY the code form after stepping up: {describe(value)}")
    kind, value = submit_otp(session, value, fresh_code(PRIYA_TOTP_SECRET), redirect_uri)
    code = assert_callback_with_code(kind, value, state2, "2: step-up to gold")
    tokens = exchange_code(base, realm, code, client_id, redirect_uri)
    acr = decode_jwt_payload(tokens["id_token"]).get("acr")
    if acr != "gold":
        raise RuntimeError(f"2: expected acr=gold after step-up, got {acr!r}")
    print("  2: same session, request gold -> only code form -> acr=gold")

    # 3. request gold again immediately -> no prompt -> acr=gold
    state3 = "oracle-3-gold-again"
    url = auth_url(base, realm, state3, client_id, redirect_uri,
                   claims={"id_token": {"acr": {"essential": True, "values": ["gold"]}}})
    resp = session.get(url, timeout=TIMEOUT, allow_redirects=False)
    relax(session)
    kind, value = follow(session, resp, redirect_uri)
    if kind != "callback":
        raise RuntimeError(f"3: expected no prompt re-requesting gold immediately: {describe(value)}")
    code = assert_callback_with_code(kind, value, state3, "3: gold again immediately")
    tokens = exchange_code(base, realm, code, client_id, redirect_uri)
    acr = decode_jwt_payload(tokens["id_token"]).get("acr")
    if acr != "gold":
        raise RuntimeError(f"3: expected acr still gold, got {acr!r}")
    print("  3: request gold again immediately -> no prompt -> acr=gold")

    # 4. fresh session requesting gold -> password then code -> acr=gold
    state4 = "oracle-4-fresh-gold"
    session4, kind, value = start(base, realm, state4, client_id, redirect_uri,
                                  claims={"id_token": {"acr": {"essential": True, "values": ["gold"]}}})
    if kind != "page" or not form_tag(value, PASSWORD_FORM):
        raise RuntimeError(f"4: expected password form on fresh session: {describe(value)}")
    kind, value = submit_password(session4, value, PRIYA, PRIYA_PASSWORD, redirect_uri)
    if kind != "page" or not form_tag(value, OTP_FORM):
        raise RuntimeError(f"4: expected code form after password: {describe(value)}")
    kind, value = submit_otp(session4, value, fresh_code(PRIYA_TOTP_SECRET), redirect_uri)
    code = assert_callback_with_code(kind, value, state4, "4: fresh session gold")
    tokens = exchange_code(base, realm, code, client_id, redirect_uri)
    acr = decode_jwt_payload(tokens["id_token"]).get("acr")
    if acr != "gold":
        raise RuntimeError(f"4: expected acr=gold on fresh session, got {acr!r}")
    print("  4: fresh session requesting gold -> password then code -> acr=gold")

    # 5. wrong code at the gold step -> rejected, no authorization code
    state5 = "oracle-5-wrong-code"
    session5, kind, value = start(base, realm, state5, client_id, redirect_uri,
                                  claims={"id_token": {"acr": {"essential": True, "values": ["gold"]}}})
    if kind != "page" or not form_tag(value, PASSWORD_FORM):
        raise RuntimeError(f"5: expected password form: {describe(value)}")
    kind, value = submit_password(session5, value, PRIYA, PRIYA_PASSWORD, redirect_uri)
    if kind != "page" or not form_tag(value, OTP_FORM):
        raise RuntimeError(f"5: expected code form after password: {describe(value)}")
    kind, value = submit_otp(session5, value, wrong_code(PRIYA_TOTP_SECRET), redirect_uri)
    if kind == "callback":
        raise RuntimeError("5: a WRONG code unexpectedly completed the login")
    if not form_tag(value, OTP_FORM):
        raise RuntimeError(f"5: after a wrong code the code form was not shown again: {describe(value)}")
    print("  5: wrong code at the gold step -> rejected")

    # 6. acme-payments, no acr requested -> code demanded anyway -> acr=gold
    state6 = "oracle-6-payments-no-acr"
    session6, kind, value = start(base, realm, state6, PAYMENTS_CLIENT_ID, PAYMENTS_REDIRECT_URI)
    if kind != "page" or not form_tag(value, PASSWORD_FORM):
        raise RuntimeError(f"6: expected password form for acme-payments: {describe(value)}")
    kind, value = submit_password(session6, value, PRIYA, PRIYA_PASSWORD, PAYMENTS_REDIRECT_URI)
    if kind != "page" or not form_tag(value, OTP_FORM):
        raise RuntimeError(f"6: acme-payments did not demand the code with no acr requested: {describe(value)}")
    kind, value = submit_otp(session6, value, fresh_code(PRIYA_TOTP_SECRET), PAYMENTS_REDIRECT_URI)
    code = assert_callback_with_code(kind, value, state6, "6: acme-payments forced gold")
    tokens = exchange_code(base, realm, code, PAYMENTS_CLIENT_ID, PAYMENTS_REDIRECT_URI)
    acr = decode_jwt_payload(tokens["id_token"]).get("acr")
    if acr != "gold":
        raise RuntimeError(f"6: expected acr=gold for acme-payments, got {acr!r}")
    print("  6: acme-payments, no acr requested -> code demanded anyway -> acr=gold")

    # 6b. acme-payments, explicitly asking for only silver -> still forced to gold
    # (catches the documented wrong solution: default.acr.values instead of minimum.acr.value)
    state6b = "oracle-6b-payments-explicit-silver"
    session6b, kind, value = start(base, realm, state6b, PAYMENTS_CLIENT_ID, PAYMENTS_REDIRECT_URI,
                                   acr_values="silver")
    if kind != "page" or not form_tag(value, PASSWORD_FORM):
        raise RuntimeError(f"6b: expected password form for acme-payments: {describe(value)}")
    kind, value = submit_password(session6b, value, PRIYA, PRIYA_PASSWORD, PAYMENTS_REDIRECT_URI)
    if kind != "page" or not form_tag(value, OTP_FORM):
        raise RuntimeError(
            f"6b: acme-payments explicitly asked for silver but was not forced to gold "
            f"(minimum.acr.value is probably set via default.acr.values instead - that is "
            f"only a browser-rewritable default, not enforcement): {describe(value)}")
    kind, value = submit_otp(session6b, value, fresh_code(PRIYA_TOTP_SECRET), PAYMENTS_REDIRECT_URI)
    code = assert_callback_with_code(kind, value, state6b, "6b: acme-payments forced gold despite explicit silver")
    tokens = exchange_code(base, realm, code, PAYMENTS_CLIENT_ID, PAYMENTS_REDIRECT_URI)
    acr = decode_jwt_payload(tokens["id_token"]).get("acr")
    if acr != "gold":
        raise RuntimeError(f"6b: expected acr=gold despite explicit silver request, got {acr!r}")
    print("  6b: acme-payments explicitly asking for silver -> still forced to gold")

    # 7. essential, unmapped acr ('platinum') -> authentication error, not a login
    state7 = "oracle-7-unmapped-acr"
    session7, kind, value = start(base, realm, state7, client_id, redirect_uri,
                                  claims={"id_token": {"acr": {"essential": True, "values": ["platinum"]}}})
    if kind == "callback":
        query = urllib.parse.parse_qs(urllib.parse.urlparse(value).query)
        if "error" not in query:
            raise RuntimeError(f"7: unmapped essential acr reached callback with no error: {value[:300]}")
    else:
        if form_tag(value, PASSWORD_FORM):
            raise RuntimeError(
                f"7: unmapped essential acr ('platinum') produced the normal password form "
                f"instead of an authentication error: {describe(value)}")
    print("  7: essential, unmapped acr ('platinum') -> authentication error")

    # 9/users: priya and morgan still exist, enabled, keep their passwords
    state9a = "oracle-9-priya-password-unchanged"
    session9a, kind, value = start(base, realm, state9a, client_id, redirect_uri)
    kind, value = submit_password(session9a, value, PRIYA, PRIYA_PASSWORD, redirect_uri)
    if kind != "callback":
        raise RuntimeError(f"9: priya's original password no longer works: {describe(value)}")
    print("  9: priya keeps her original password")

    state9b = "oracle-9-morgan-password-unchanged"
    session9b, kind, value = start(base, realm, state9b, client_id, redirect_uri)
    kind, value = submit_password(session9b, value, MORGAN, MORGAN_PASSWORD, redirect_uri)
    if kind != "callback":
        raise RuntimeError(f"9: morgan's original password no longer works: {describe(value)}")
    print("  9: morgan keeps his original password")


def check_realms_and_users(base, realm, token, admin_realm):
    realms = requests.get(f"{base}/admin/realms", headers=auth(token), timeout=TIMEOUT).json()
    names = sorted(r["realm"] for r in realms)
    if names != sorted([admin_realm, realm]):
        raise RuntimeError(f"expected only {[admin_realm, realm]!r} realms, found {names!r}")

    for username in (PRIYA, MORGAN):
        users = requests.get(f"{base}/admin/realms/{realm}/users",
                             params={"username": username, "exact": "true"},
                             headers=auth(token), timeout=TIMEOUT).json()
        if not users or not users[0].get("enabled"):
            raise RuntimeError(f"user {username!r} missing or disabled: {users}")


def main():
    creds = load_settings(CREDS_PATH)
    base = creds["keycloak_base_url"].rstrip("/")
    realm = creds["target_realm"]
    client_id, redirect_uri = creds["app_client_id"], creds["app_redirect_uri"]
    token = get_admin_token(base, creds["admin_realm"], creds["admin_username"], creds["admin_password"])

    print("Checking the realm's default 'acr' client scope has the oidc-acr-mapper...")
    ensure_acr_mapper_present(base, realm, token)

    print(f"Authoring '{FLOW_ALIAS}' (Level 1 then Level 2, lowest level first)...")
    flow_id = build_flow(base, realm, token)

    print("Setting realm acr.loa.map and access-token lifespan...")
    set_acr_loa_map_and_token_lifespan(base, realm, token)

    print(f"Binding '{FLOW_ALIAS}' as the realm's browser flow...")
    bind_realm_flow(base, realm, token, FLOW_ALIAS)

    print("Pinning acme-payments to always require gold (minimum.acr.value)...")
    pin_client_to_gold(base, realm, token, PAYMENTS_CLIENT_ID)

    print("Checking realms/users are unchanged...")
    check_realms_and_users(base, realm, token, creds["admin_realm"])

    print("Driving every requirement end-to-end...")
    self_check(base, realm, client_id, redirect_uri)
    print("Done.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ORACLE FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
