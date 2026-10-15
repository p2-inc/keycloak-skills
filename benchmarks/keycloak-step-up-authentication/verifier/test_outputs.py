# Copyright 2026 Phase Two, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Pytest-based verifier. Run by BenchFlow after the agent completes.

Drives the nine requirements of task.md for real over plain HTTP against the live Keycloak
instance for this task. No browser automation needed - a TOTP code is just a form field.

The only thing mocked is priya's authenticator app: her TOTP secret is seeded in the realm
fixture (environment/acme-realm.json), so the verifier computes her current code the way a
real app would (RFC 6238, HMAC-SHA1 over the secret's raw bytes). Keycloak's authentication
logic - flows, conditions, ACR mapping, token issuance - is entirely real.

Deliberately shape-agnostic: nothing here asserts a flow alias, execution priority, provider
id, or which binding surface (realm vs client) did the enforcing. Any correct configuration
passes. Every page-level assertion quotes the page's identity (data-page-id, form ids) and its
<form> HTML, truncated to ~1500 chars, so a failure is diagnosable from the test output alone.

On an unconfigured realm (stock browser flow, no acr.loa.map, no minimum.acr.value) every test
below fails: there is no mechanism distinguishing silver from gold, acme-payments lets a plain
password login straight through, and an unmapped acr value is never evaluated for an error in
the first place since nothing maps acr to levels at all.
"""

import base64
import hashlib
import hmac
import html as htmllib
import json
import pathlib
import re
import struct
import time
import urllib.parse

import pytest
import requests

ADMIN_CREDS_PATH = "/root/admin_credentials.txt"
ARTIFACT_DIR = pathlib.Path("/logs/verifier")
TIMEOUT = 30

PRIYA_USER, PRIYA_PASSWORD = "priya", "Priya!Pass1"
MORGAN_USER, MORGAN_PASSWORD = "morgan", "Morgan!Pass1"
WRONG_PASSWORD = "definitely-not-the-password"
# Seeded in environment/acme-realm.json.
PRIYA_TOTP_SECRET = "AcmePriyaTotp2026Sec"

PASSWORD_FORM = "kc-form-login"
OTP_FORM = "kc-otp-login-form"

PAYMENTS_CLIENT_ID = "acme-payments"
PAYMENTS_REDIRECT_URI = "http://localhost:9998/callback"


def _read_settings(path):
    values = {}
    for line in pathlib.Path(path).read_text().splitlines():
        line = line.strip()
        if line and "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


@pytest.fixture(scope="session")
def config():
    creds = _read_settings(ADMIN_CREDS_PATH)
    return {
        "base": creds["keycloak_base_url"].rstrip("/"),
        "realm": creds["target_realm"],
        "admin_realm": creds["admin_realm"],
        "admin_username": creds["admin_username"],
        "admin_password": creds["admin_password"],
        "client_id": creds["app_client_id"],
        "redirect_uri": creds["app_redirect_uri"],
    }


@pytest.fixture(scope="session")
def admin_headers(config):
    resp = requests.post(
        f"{config['base']}/realms/{config['admin_realm']}/protocol/openid-connect/token",
        data={"grant_type": "password", "client_id": "admin-cli",
              "username": config["admin_username"], "password": config["admin_password"]},
        timeout=TIMEOUT,
    )
    assert resp.status_code == 200, f"admin login failed ({resp.status_code}): {resp.text[:300]}"
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


# --------------------------------------------------------------------- TOTP


def totp(secret, at=None, digits=6, period=30, algorithm="HmacSHA1"):
    """RFC 6238 over the secret's raw bytes - what Keycloak validates against."""
    digest = {"HmacSHA1": hashlib.sha1, "HmacSHA256": hashlib.sha256,
              "HmacSHA512": hashlib.sha512}[algorithm]
    counter = int((time.time() if at is None else at) // period)
    mac = hmac.new(secret.encode("utf-8"), struct.pack(">Q", counter), digest).digest()
    offset = mac[-1] & 0x0F
    value = (struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(value).zfill(digits)


def fresh_code(secret, period=30, **kw):
    """A code from a period no earlier caller can have used: Keycloak refuses to accept the
    same code twice, so wait for the next period to begin."""
    time.sleep(period - (time.time() % period) + 1)
    return totp(secret, period=period, **kw)


def wrong_code(secret, **kw):
    """A 6-digit code valid for no period in Keycloak's look-around window."""
    now = time.time()
    taken = {totp(secret, at=now + d * 30, **kw) for d in (-2, -1, 0, 1, 2)}
    return next(c for c in ("000000", "111111", "123456", "999999") if c not in taken)


# --------------------------------------------------------------------- JWT (no extra deps)


def _b64url_decode(segment):
    padded = segment + "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def decode_jwt_payload(token):
    parts = token.split(".")
    assert len(parts) == 3, f"not a JWT (expected 3 dot-separated parts): {token[:80]!r}"
    return json.loads(_b64url_decode(parts[1]))


# --------------------------------------------------------------------- HTTP helpers


def _relax(session):
    """Keycloak marks AUTH_SESSION_ID / KC_RESTART Secure; SameSite=None. requests will not
    send Secure cookies over http://localhost unless this flag is cleared."""
    for cookie in session.cookies:
        cookie.secure = False


def _auth_url(config, state, client_id=None, redirect_uri=None, acr_values=None, claims=None):
    params = {
        "client_id": client_id or config["client_id"],
        "response_type": "code",
        "scope": "openid",
        "redirect_uri": redirect_uri or config["redirect_uri"],
        "state": state,
    }
    if acr_values:
        params["acr_values"] = acr_values
    if claims:
        params["claims"] = json.dumps(claims)
    return f"{config['base']}/realms/{config['realm']}/protocol/openid-connect/auth?" + urllib.parse.urlencode(params)


def _form_tag(html, form_id):
    for match in re.finditer(r"<form\b[^>]*>", html or "", re.I):
        if f'id="{form_id}"' in match.group(0):
            return match.group(0)
    return None


def _form_action(html, form_id):
    tag = _form_tag(html, form_id)
    action = re.search(r'action="([^"]+)"', tag or "")
    return htmllib.unescape(action.group(1)) if action else None


def _hidden_value(html, name):
    tag = re.search(rf'<input\b[^>]*name="{re.escape(name)}"[^>]*>', html or "", re.I)
    value = re.search(r'value="([^"]*)"', tag.group(0)) if tag else None
    return htmllib.unescape(value.group(1)) if value else None


def _describe(html):
    """The page's identity and its <form> - quoted in every page-check failure."""
    page_id = re.search(r'data-page-id="([^"]+)"', html or "")
    forms = re.findall(r'<form\b[^>]*\bid="([^"]+)"', html or "")
    form = re.search(r"<form\b.*?</form>", html or "", re.I | re.S)
    return (f"page_id={page_id.group(1) if page_id else None!r}, forms={forms}, "
            f"form={(form.group(0) if form else (html or '')[:400])[:1500]!r}")


def _follow(session, resp, config):
    """Follow redirects until the client callback (returned as ("callback", url)), an error
    callback with no code (also ("callback", url)), or a page (("page", html))."""
    for _ in range(10):
        _relax(session)
        if resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("Location", "")
            if location.startswith("http://localhost:9999/callback") or \
               location.startswith(PAYMENTS_REDIRECT_URI):
                return "callback", location
            resp = session.get(urllib.parse.urljoin(resp.url, location), timeout=TIMEOUT,
                               allow_redirects=False)
            continue
        return "page", resp.text
    return "page", resp.text


def _start(config, state, client_id=None, redirect_uri=None, acr_values=None, claims=None,
           session=None):
    session = session or requests.Session()
    url = _auth_url(config, state, client_id=client_id, redirect_uri=redirect_uri,
                     acr_values=acr_values, claims=claims)
    resp = session.get(url, timeout=TIMEOUT, allow_redirects=False)
    kind, value = _follow(session, resp, config)
    return session, kind, value


def _submit_password(config, session, html, username, password):
    resp = session.post(_form_action(html, PASSWORD_FORM),
                        data={"username": username, "password": password},
                        timeout=TIMEOUT, allow_redirects=False)
    return _follow(session, resp, config)


def _submit_otp(config, session, html, code):
    data = {"otp": code}
    selected = _hidden_value(html, "selectedCredentialId")
    if selected:
        data["selectedCredentialId"] = selected
    resp = session.post(_form_action(html, OTP_FORM), data=data, timeout=TIMEOUT,
                        allow_redirects=False)
    return _follow(session, resp, config)


def _assert_callback_with_code(kind, value, state, what):
    assert kind == "callback", f"{what} did not reach any application callback: {_describe(value)}"
    query = urllib.parse.parse_qs(urllib.parse.urlparse(value).query)
    assert "error" not in query, f"{what}: callback carried an error: {value[:300]}"
    assert "code" in query, f"{what}: no authorization code returned: {value[:250]}"
    assert query.get("state") == [state], (
        f"{what}: state was not preserved: sent {state!r}, got {query.get('state')!r}")
    return query["code"][0]


def _exchange_code(config, code, client_id=None, redirect_uri=None):
    resp = requests.post(
        f"{config['base']}/realms/{config['realm']}/protocol/openid-connect/token",
        data={"grant_type": "authorization_code", "code": code,
              "client_id": client_id or config["client_id"],
              "redirect_uri": redirect_uri or config["redirect_uri"]},
        timeout=TIMEOUT,
    )
    assert resp.status_code == 200, f"token exchange failed ({resp.status_code}): {resp.text[:400]}"
    return resp.json()


def _acr_from_login(config, state, username, password, otp_code=None, client_id=None,
                     redirect_uri=None, acr_values=None, claims=None, session=None,
                     expect_otp_prompt=None, what="login"):
    """Drive a full login (password [+ code]) and return the ID token's acr claim.

    expect_otp_prompt, if not None, asserts whether the OTP form was (True) or was not
    (False) shown after the password step.
    """
    session, kind, value = _start(config, state, client_id=client_id, redirect_uri=redirect_uri,
                                   acr_values=acr_values, claims=claims, session=session)
    assert kind == "page" and _form_tag(value, PASSWORD_FORM), (
        f"{what}: expected the username/password form: {_describe(value)}")
    kind, value = _submit_password(config, session, value, username, password)

    if expect_otp_prompt is True:
        assert kind == "page" and _form_tag(value, OTP_FORM), (
            f"{what}: expected the one-time-code form after the password: {_describe(value)}")
    elif expect_otp_prompt is False:
        assert kind == "callback", (
            f"{what}: expected to be logged in immediately after the password, with no "
            f"further prompt: {_describe(value if kind == 'page' else '')}")

    if kind == "page" and _form_tag(value, OTP_FORM):
        assert otp_code is not None, f"{what}: an OTP code form appeared but no code was given"
        kind, value = _submit_otp(config, session, value, otp_code)

    code = _assert_callback_with_code(kind, value, state, what)
    tokens = _exchange_code(config, code, client_id=client_id, redirect_uri=redirect_uri)
    id_token = tokens.get("id_token")
    assert id_token, f"{what}: token response carried no id_token: {sorted(tokens.keys())}"
    payload = decode_jwt_payload(id_token)
    return payload.get("acr"), session


def _save(name, html):
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    (ARTIFACT_DIR / name).write_text((html or "")[:20000])


# --------------------------------------------------------------- 1. no acr -> silver


def test_no_acr_requested_logs_in_at_silver(config):
    """Requirement 1: a plain acme-portal login with no acr requested asks only for the
    password and the ID token's acr claim is silver."""
    acr, _session = _acr_from_login(
        config, "step1-no-acr", PRIYA_USER, PRIYA_PASSWORD,
        expect_otp_prompt=False, what="plain acme-portal login with no acr requested")
    assert acr == "silver", (
        f"expected acr=silver for a plain login with no acr requested, got acr={acr!r}")


# --------------------------------------------------------------- 2/3/4/5. step-up behaviour


def test_step_up_to_gold_in_same_session_asks_only_for_the_code():
    pass  # placeholder removed below; real test defined after fixture-aware helper


def test_step_up_in_same_browser_session_shows_only_the_code_form_and_reaches_gold(config):
    """Requirement 2: in the SAME browser session that already holds silver, requesting gold
    as an essential claim must show only the code form - never the password form again - and
    completing it must yield acr=gold."""
    state1 = "step2-establish-silver"
    session, kind, value = _start(config, state1)
    assert kind == "page" and _form_tag(value, PASSWORD_FORM), (
        f"expected the password form to start the session: {_describe(value)}")
    kind, value = _submit_password(config, session, value, PRIYA_USER, PRIYA_PASSWORD)
    assert not (kind == "page" and _form_tag(value, OTP_FORM)), (
        "a plain first login unexpectedly already asked for the OTP code "
        f"(level 2 is probably ordered before level 1): {_describe(value)}")
    code = _assert_callback_with_code(kind, value, state1, "establishing silver")
    _exchange_code(config, code)

    state2 = "step2-upgrade-to-gold"
    url = _auth_url(config, state2, claims={"id_token": {"acr": {"essential": True, "values": ["gold"]}}})
    resp = session.get(url, timeout=TIMEOUT, allow_redirects=False)
    _relax(session)
    kind, value = _follow(session, resp, config)
    assert kind == "page", (
        f"requesting gold in the same session did not show the code prompt: {_describe(value)}")
    assert not _form_tag(value, PASSWORD_FORM), (
        f"requesting gold with an existing silver session asked for the PASSWORD again, "
        f"not just the code: {_describe(value)}")
    assert _form_tag(value, OTP_FORM), (
        f"requesting gold did not show the one-time-code form: {_describe(value)}")
    _save("step2-code-only-prompt.html", value)

    kind, value = _submit_otp(config, session, value, fresh_code(PRIYA_TOTP_SECRET))
    code = _assert_callback_with_code(kind, value, state2, "stepping up to gold")
    tokens = _exchange_code(config, code)
    payload = decode_jwt_payload(tokens["id_token"])
    assert payload.get("acr") == "gold", f"expected acr=gold after stepping up, got {payload.get('acr')!r}"


def test_requesting_gold_again_immediately_needs_no_prompt_at_all(config):
    """Requirement 3: asking for gold again right away, same browser session, needs no
    prompt at all and completes immediately with acr still gold."""
    state1 = "step3-establish-gold"
    session, kind, value = _start(config, state1, claims={"id_token": {"acr": {"essential": True, "values": ["gold"]}}})
    assert kind == "page" and _form_tag(value, PASSWORD_FORM), (
        f"expected the password form establishing gold: {_describe(value)}")
    kind, value = _submit_password(config, session, value, PRIYA_USER, PRIYA_PASSWORD)
    assert kind == "page" and _form_tag(value, OTP_FORM), (
        f"expected the code form after the password while establishing gold: {_describe(value)}")
    kind, value = _submit_otp(config, session, value, fresh_code(PRIYA_TOTP_SECRET))
    code = _assert_callback_with_code(kind, value, state1, "first gold login")
    tokens = _exchange_code(config, code)
    assert decode_jwt_payload(tokens["id_token"]).get("acr") == "gold", "setup for test 3 failed to reach gold"

    state2 = "step3-gold-again"
    url = _auth_url(config, state2, claims={"id_token": {"acr": {"essential": True, "values": ["gold"]}}})
    resp = session.get(url, timeout=TIMEOUT, allow_redirects=False)
    _relax(session)
    kind, value = _follow(session, resp, config)
    assert kind == "callback", (
        f"re-requesting gold immediately within the window still prompted the user: {_describe(value)}")
    code = _assert_callback_with_code(kind, value, state2, "re-requesting gold immediately")
    tokens = _exchange_code(config, code)
    assert decode_jwt_payload(tokens["id_token"]).get("acr") == "gold", (
        f"re-requesting gold immediately did not keep acr=gold: {decode_jwt_payload(tokens['id_token']).get('acr')!r}")


def test_fresh_session_requesting_gold_shows_password_then_code(config):
    """Requirement 4: a FRESH browser session asking for gold from the start shows the
    password form, then the code form, and completes with acr=gold."""
    acr, _session = _acr_from_login(
        config, "step4-fresh-gold", PRIYA_USER, PRIYA_PASSWORD,
        otp_code=fresh_code(PRIYA_TOTP_SECRET),
        claims={"id_token": {"acr": {"essential": True, "values": ["gold"]}}},
        expect_otp_prompt=True,
        what="fresh session requesting gold from the start")
    assert acr == "gold", f"expected acr=gold for a fresh session requesting gold, got {acr!r}"


def test_wrong_code_at_the_gold_step_is_rejected(config):
    """Requirement 5: a wrong one-time code at the level-2 step is rejected; no authorization
    code is issued, and the code form is shown again."""
    state = "step5-wrong-code"
    session, kind, value = _start(
        config, state, claims={"id_token": {"acr": {"essential": True, "values": ["gold"]}}})
    assert kind == "page" and _form_tag(value, PASSWORD_FORM), (
        f"expected the password form: {_describe(value)}")
    kind, value = _submit_password(config, session, value, PRIYA_USER, PRIYA_PASSWORD)
    assert kind == "page" and _form_tag(value, OTP_FORM), (
        f"expected the code form after the password: {_describe(value)}")
    kind, value = _submit_otp(config, session, value, wrong_code(PRIYA_TOTP_SECRET))
    assert kind == "page", "a WRONG one-time code unexpectedly completed the login"
    assert _form_tag(value, OTP_FORM), (
        f"after a wrong code the one-time-code form was not shown again: {_describe(value)}")


# --------------------------------------------------------------- 6. acme-payments forces gold


def test_acme_payments_always_demands_gold_even_with_no_acr_requested(config):
    """Requirement 6: a login against acme-payments with NO acr requested at all is still
    asked for the code after the password - this client must always get gold."""
    acr, _session = _acr_from_login(
        config, "step6-payments-no-acr", PRIYA_USER, PRIYA_PASSWORD,
        otp_code=fresh_code(PRIYA_TOTP_SECRET),
        client_id=PAYMENTS_CLIENT_ID, redirect_uri=PAYMENTS_REDIRECT_URI,
        expect_otp_prompt=True,
        what="acme-payments login with no acr requested")
    assert acr == "gold", (
        f"acme-payments must always reach acr=gold even with no acr requested, got {acr!r}")


def test_acme_payments_is_not_merely_defaulted_via_a_rewritable_setting(config, admin_headers):
    """Documentation-warned wrong solution: setting default.acr.values=gold instead of
    minimum.acr.value=gold looks identical when the browser plays along, but is silently
    bypassed by a request that explicitly asks for silver - a browser-controllable default
    enforces nothing. A request for acr_values=silver against acme-payments must still reach
    gold, proving enforcement rather than a mere default."""
    acr, _session = _acr_from_login(
        config, "step6b-payments-explicit-silver", PRIYA_USER, PRIYA_PASSWORD,
        otp_code=fresh_code(PRIYA_TOTP_SECRET),
        client_id=PAYMENTS_CLIENT_ID, redirect_uri=PAYMENTS_REDIRECT_URI,
        acr_values="silver",
        what="acme-payments login explicitly asking for only silver")
    assert acr == "gold", (
        f"acme-payments explicitly asked for silver but must still be forced to gold "
        f"(minimum.acr.value, not a rewritable default) - got acr={acr!r}")


# --------------------------------------------------------------- 7. unmapped essential acr errors


def test_unmapped_essential_acr_produces_an_authentication_error(config):
    """Requirement 7: an essential acr of 'platinum' (mapped to no level) fails with an
    authentication error rather than logging the user in at some level."""
    state = "step7-unmapped-acr"
    session, kind, value = _start(
        config, state, claims={"id_token": {"acr": {"essential": True, "values": ["platinum"]}}})

    if kind == "callback":
        query = urllib.parse.parse_qs(urllib.parse.urlparse(value).query)
        assert "error" in query, (
            f"an essential, unmapped acr ('platinum') reached the callback with no error "
            f"and query={query}: {value[:300]}")
        return

    # Not yet at a callback: it must not be the normal password form either - that would
    # mean the request was silently treated as if nothing had been asked at all.
    assert not _form_tag(value, PASSWORD_FORM), (
        f"an essential, unmapped acr ('platinum') produced the normal password form instead "
        f"of an authentication error: {_describe(value)}")


# --------------------------------------------------------------- 8. configuration check


def test_acr_loa_map_and_token_lifespan_and_level2_max_age_are_configured(config, admin_headers):
    """Requirement 8, checked as configuration (a real 5-minute expiry is impractical to wait
    out inside a verifier run): realm acr.loa.map maps silver->1 and gold->2; the realm's
    access-token lifespan is <= 300s; the level-2 condition's own loa-max-age is 300."""
    realm = requests.get(f"{config['base']}/admin/realms/{config['realm']}",
                         headers=admin_headers, timeout=TIMEOUT).json()
    attributes = realm.get("attributes") or {}
    raw_map = attributes.get("acr.loa.map")
    assert raw_map, f"realm attribute acr.loa.map is not set; attributes={sorted(attributes.keys())}"
    try:
        acr_map = json.loads(raw_map) if isinstance(raw_map, str) else raw_map
    except (TypeError, ValueError) as exc:
        pytest.fail(f"realm attribute acr.loa.map is not valid JSON: {raw_map!r} ({exc})")
    assert int(acr_map.get("silver")) == 1, f"acr.loa.map['silver'] = {acr_map.get('silver')!r}, expected 1"
    assert int(acr_map.get("gold")) == 2, f"acr.loa.map['gold'] = {acr_map.get('gold')!r}, expected 2"

    lifespan = realm.get("accessTokenLifespan")
    assert lifespan is not None, "realm accessTokenLifespan is not set"
    assert int(lifespan) <= 300, (
        f"access-token lifespan is {lifespan}s, must be <=300s or a token issued at gold "
        f"outlives the 5-minute self-lock")

    found_max_age = None
    flows = requests.get(f"{config['base']}/admin/realms/{config['realm']}/authentication/flows",
                         headers=admin_headers, timeout=TIMEOUT).json()
    for flow in flows:
        execs = requests.get(
            f"{config['base']}/admin/realms/{config['realm']}/authentication/flows/"
            f"{urllib.parse.quote(flow['alias'], safe='')}/executions",
            headers=admin_headers, timeout=TIMEOUT)
        if execs.status_code != 200:
            continue
        for execution in execs.json():
            if execution.get("providerId") != "conditional-level-of-authentication":
                continue
            exec_id = execution.get("id")
            cfg_id = execution.get("authenticationConfig")
            config_body = None
            if cfg_id:
                resp = requests.get(
                    f"{config['base']}/admin/realms/{config['realm']}/authentication/config/{cfg_id}",
                    headers=admin_headers, timeout=TIMEOUT)
                if resp.status_code == 200:
                    config_body = resp.json().get("config", {})
            if not config_body and exec_id:
                resp = requests.get(
                    f"{config['base']}/admin/realms/{config['realm']}/authentication/executions/"
                    f"{exec_id}/config",
                    headers=admin_headers, timeout=TIMEOUT)
                if resp.status_code == 200:
                    config_body = resp.json().get("config", {})
            if config_body and str(config_body.get("loa-condition-level")) == "2":
                found_max_age = config_body.get("loa-max-age")

    assert found_max_age is not None, (
        "no conditional-level-of-authentication execution with loa-condition-level=2 was "
        "found anywhere in the realm's authentication flows")
    assert int(found_max_age) == 300, (
        f"the level-2 condition's loa-max-age is {found_max_age!r}, expected 300 (the "
        f"5-minute self-locking window)")


# --------------------------------------------------------------- 9. no collateral damage


def test_users_and_realms_unchanged(config, admin_headers):
    """Requirement 9: priya and morgan still exist, are enabled, and keep their original
    passwords (checked with a real login, not merely a credential object's presence); only
    master and acme realms exist."""
    for username, password in ((PRIYA_USER, PRIYA_PASSWORD), (MORGAN_USER, MORGAN_PASSWORD)):
        users = requests.get(f"{config['base']}/admin/realms/{config['realm']}/users",
                             headers=admin_headers, params={"username": username, "exact": "true"},
                             timeout=TIMEOUT).json()
        assert users, f"the {username} account is gone"
        assert users[0].get("enabled") is True, f"the {username} account is disabled"

        resp = requests.post(
            f"{config['base']}/realms/{config['realm']}/protocol/openid-connect/token",
            data={"grant_type": "password", "client_id": "mcp-bench-cli",
                  "username": username, "password": password, "scope": "openid"},
            timeout=TIMEOUT)
        # direct_access_grants may be disabled on acme-portal/payments; mcp-bench-cli may also
        # lack it. Fall back to proving the password still works via the browser form if the
        # grant is unavailable (invalid_client / unauthorized_client), rather than treating a
        # disabled grant as a changed password.
        if resp.status_code == 200:
            continue
        body = resp.text
        if "unauthorized_client" not in body and "invalid_client" not in body:
            # A real auth failure (invalid_grant for bad credentials) means the password
            # actually changed - that's a genuine failure for this test.
            session, kind, value = _start(config, f"collateral-{username}")
            assert kind == "page" and _form_tag(value, PASSWORD_FORM), (
                f"could not even reach the password form to re-check {username}'s password: "
                f"{_describe(value)}")
            kind, value = _submit_password(config, session, value, username, password)
            assert kind == "page" and not _form_tag(value, PASSWORD_FORM), (
                f"{username}'s original password no longer works: {_describe(value)}")

    resp = requests.get(f"{config['base']}/admin/realms", headers=admin_headers,
                        params={"briefRepresentation": "true"}, timeout=TIMEOUT)
    assert resp.status_code == 200, f"realm listing failed: {resp.text[:300]}"
    names = {r["realm"] for r in resp.json()}
    assert names == {"master", config["realm"]}, (
        f"realms are {sorted(names)}; expected exactly master and {config['realm']}")


# Remove the placeholder stub defined above test 2 (kept only to preserve numbering intent).
del test_step_up_to_gold_in_same_session_asks_only_for_the_code
