#!/usr/bin/env python3

# Copyright 2026 Phase Two, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Check a magic-link login end to end, once, and say whether you are done.

    verify_magic_link.py --realm myrealm --client my-app \
        --redirect-uri http://localhost:9999/callback \
        --known staff@customer.example --unknown nobody@customer.example \
        [--mail-dir /var/mail-capture] [--link URL] \
        [--admin-token TOKEN] [--base http://localhost:8080/auth]

Prints one PASS/FAIL line per check and exits 0 only if every check that could
run passed. If it exits 0, the configuration is done — stop re-inspecting it.

  --mail-dir        a directory an SMTP capture server writes one file per
                    message into; the script waits for the known address's
                    mail there and follows the link itself
  --link            the magic link copied from a real inbox, if there is no
                    capture directory (run once without it to trigger the mail)
  --admin-token     a master-realm admin access token (or set ADMIN_TOKEN), to
                    confirm no account was created for --unknown (the login
                    page cannot show this)

What it checks:

  1. the known address gets a login page with no password field
  2. submitting it shows the "check your email" page
  3. mail arrives for it with a login-actions/action-token link
  4. following that link lands on --redirect-uri with an authorization code
  5. the unknown address gets the same page as the known one
  6. no mail went to the unknown address
  7. no user exists for the unknown address (needs --admin-token)

Like browser_login.py, it clears the Secure flag on Keycloak's auth cookies
after each response: urllib will not send them over http://localhost, and
every form POST then fails with "Cookie not found".
"""

import argparse
import http.cookiejar
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT = 30
LINK = re.compile(r'https?://[^\s"\'<>\\]+login-actions/action-token[^\s"\'<>\\]*')


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # surface the 3xx to the caller instead of following it


class Response:
    def __init__(self, status, headers, body):
        self.status_code = status
        self.headers = headers
        self.text = body.decode("utf-8", "replace")

    def json(self):
        return json.loads(self.text)


class Session:
    """The slice of a `requests` session these scripts need, on the standard
    library alone, so running them never needs a `pip install`."""

    def __init__(self):
        self.cookies = http.cookiejar.CookieJar()
        cookies = urllib.request.HTTPCookieProcessor(self.cookies)
        self._follow = urllib.request.build_opener(cookies)
        self._stay = urllib.request.build_opener(cookies, _NoRedirect())

    def request(self, method, url, params=None, data=None, headers=None,
                allow_redirects=True, timeout=None):
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        body = urllib.parse.urlencode(data).encode() if data is not None else None
        req = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
        opener = self._follow if allow_redirects else self._stay
        try:
            with opener.open(req, timeout=timeout) as resp:
                return Response(resp.status, resp.headers, resp.read())
        except urllib.error.HTTPError as err:
            return Response(err.code, err.headers, err.read())

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)

failures = 0


def report(ok, what):
    global failures
    print(("PASS  " if ok else "FAIL  ") + what)
    if not ok:
        failures += 1


def insecure_cookies(session):
    for cookie in session.cookies:
        cookie.secure = False


def form_action(html):
    match = re.search(r'<form[^>]*action="([^"]+)"', html or "", re.I)
    return match.group(1).replace("&amp;", "&") if match else None


def start_login(args, email):
    """Open the client's login page, submit the email, return both pages."""
    session = Session()
    params = {"client_id": args.client, "redirect_uri": args.redirect_uri,
              "response_type": "code", "scope": "openid", "state": "verify"}
    url = f"{args.base}/realms/{args.realm}/protocol/openid-connect/auth"
    page = session.get(url, params=params, timeout=TIMEOUT)
    insecure_cookies(session)
    action = form_action(page.text)
    if not action:
        return session, page.text, None
    after = session.post(action, data={"username": email}, timeout=TIMEOUT)
    insecure_cookies(session)
    return session, page.text, after.text


def visible_text(html, email=""):
    """Page text with markup stripped and the submitted address blanked out —
    the confirmation page echoes back whatever was typed, which is expected."""
    html = re.sub(r"<(script|style)\b.*?</\1>", " ", html or "", flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", html)
    if email:
        text = re.sub(re.escape(email), "<email>", text, flags=re.I)
    return re.sub(r"\s+", " ", text).strip()


def mail_files(mail_dir):
    try:
        return {os.path.join(mail_dir, n) for n in os.listdir(mail_dir)}
    except OSError:
        return set()


def mail_for(path, email):
    try:
        raw = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return None
    try:
        raw = json.dumps(json.loads(raw))  # normalise escapes so the regex sees plain URLs
        raw = raw.replace("\\/", "/").replace("\\u0026", "&")
    except ValueError:
        pass
    return raw if email.lower() in raw.lower() else None


def wait_for_link(mail_dir, before, email, seconds=20):
    deadline = time.time() + seconds
    while time.time() < deadline:
        for path in mail_files(mail_dir) - before:
            body = mail_for(path, email)
            if body:
                match = LINK.search(body.replace("&amp;", "&"))
                if match:
                    return match.group(0)
        time.sleep(1)
    return None


def follow_link(args, session, link):
    """Follow redirects by hand until one points at the app's redirect URI."""
    url = link
    for _ in range(15):
        if url.startswith(args.redirect_uri):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            return "code" in query
        response = session.get(url, allow_redirects=False, timeout=TIMEOUT)
        insecure_cookies(session)
        location = response.headers.get("Location")
        if not location:
            return False
        url = urllib.parse.urljoin(url, location)
    return False


def unknown_user_exists(args):
    token = args.admin_token
    users = Session().get(
        f"{args.base}/admin/realms/{args.realm}/users",
        params={"email": args.unknown, "exact": "true"},
        headers={"Authorization": f"Bearer {token}"}, timeout=TIMEOUT).json()
    return bool(users)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--base", default="http://localhost:8080/auth")
    parser.add_argument("--realm", required=True)
    parser.add_argument("--client", required=True)
    parser.add_argument("--redirect-uri", required=True)
    parser.add_argument("--known", required=True)
    parser.add_argument("--unknown", required=True)
    parser.add_argument("--mail-dir")
    parser.add_argument("--link")
    parser.add_argument("--admin-token", default=os.environ.get("ADMIN_TOKEN"))
    args = parser.parse_args()

    before = mail_files(args.mail_dir) if args.mail_dir else set()
    session, login_page, known_after = start_login(args, args.known)
    report('type="password"' not in login_page.lower(),
           "login page has no password field")
    report(known_after is not None, "email submitted on the login page")
    if known_after is None:
        print("      the login page had no form — is the flow bound, and does it start"
              " with an email step?")

    link = args.link
    if args.mail_dir:
        link = wait_for_link(args.mail_dir, before, args.known)
        report(link is not None, f"mail with a login link arrived for {args.known}")
        if link is None:
            print("      nothing arrived — check the realm's SMTP settings (host, port, from)")
    elif not link:
        print(f"SKIP  mail check — open {args.known}'s inbox and rerun with --link <url>")

    if link:
        report(follow_link(args, session, link),
               "the link lands on the redirect URI with an authorization code")

    before_unknown = mail_files(args.mail_dir) if args.mail_dir else set()
    _, _, unknown_after = start_login(args, args.unknown)
    report(unknown_after is not None
           and visible_text(unknown_after, args.unknown)
           == visible_text(known_after, args.known),
           "an unknown address sees exactly the same page as a known one")
    if args.mail_dir:
        time.sleep(5)
        sent = [p for p in mail_files(args.mail_dir) - before_unknown
                if mail_for(p, args.unknown)]
        report(not sent, f"no mail went to {args.unknown}")
    if args.admin_token:
        report(not unknown_user_exists(args), f"no account was created for {args.unknown}")
    else:
        print("SKIP  account check — pass --admin-token to confirm no user"
              " was created (turn off ext-magic-create-nonexistent-user if one was)")

    if failures:
        print(f"\n{failures} check(s) failed — fix those, then rerun this once.")
        return 1
    print("\nAll checks passed. The configuration is done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
