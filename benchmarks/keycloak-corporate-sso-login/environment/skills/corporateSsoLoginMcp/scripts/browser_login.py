#!/usr/bin/env python3
"""Drive a Keycloak browser login headlessly and report where each step went.

    browser_login.py --realm myrealm --client my-app \
        --redirect-uri http://localhost:9999/callback \
        --username user@customer.example [--password secret] \
        [--idp-username u --idp-password p] [--base http://localhost:8080/auth]

Prints one line per step, so you can see whether an address was routed to a
brokered identity provider or offered a password form. Exits 0 if the login
reached the redirect URI with an authorization code.

  --password              submit this on the password form, if one is shown
  --idp-username/-password  credentials to use if the flow lands on a brokered
                          provider's own login page (defaults to --username and
                          --password)

Two client-side details this handles, which otherwise waste an afternoon:

  * Keycloak's auth cookies are Secure with SameSite=None. Browsers send them
    over http://localhost anyway (loopback is a secure context); requests will
    not, and every POST fails with "Cookie not found". The flag is cleared after
    each response.
  * The route to a brokered provider takes two shapes: a page offering it as a
    link (user not yet federated), or a 302 straight at the broker endpoint with
    a login_hint (already federated). Both are followed.
"""

import argparse
import re
import sys
import urllib.parse

import requests

TIMEOUT = 30


def relax_cookies(session):
    for cookie in session.cookies:
        cookie.secure = False


def form_action(html):
    match = re.search(r'<form[^>]*action="([^"]+)"', html or "", re.I)
    return match.group(1).replace("&amp;", "&") if match else None


def absolute(url, base):
    if url.startswith("http"):
        return url
    origin = "/".join(base.split("/")[:3])
    return origin + url


def broker_link(html):
    match = re.search(r'href="([^"]*?/broker/[^"]*?/login[^"]*)"', html or "")
    return match.group(1).replace("&amp;", "&") if match else None


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base", default="http://localhost:8080/auth")
    p.add_argument("--realm", required=True)
    p.add_argument("--client", required=True)
    p.add_argument("--redirect-uri", required=True)
    p.add_argument("--username", required=True)
    p.add_argument("--password")
    p.add_argument("--idp-username")
    p.add_argument("--idp-password")
    p.add_argument("--state", default="cli-state")
    args = p.parse_args()

    base = args.base.rstrip("/")
    session = requests.Session()

    auth_url = f"{base}/realms/{args.realm}/protocol/openid-connect/auth?" + urllib.parse.urlencode({
        "client_id": args.client, "response_type": "code", "scope": "openid email",
        "redirect_uri": args.redirect_uri, "state": args.state,
        "nonce": f"nonce-{args.state}",
    })

    page = session.get(auth_url, timeout=TIMEOUT)
    relax_cookies(session)
    print(f"1. GET authorization endpoint      -> {page.status_code}")
    action = form_action(page.text)
    if not action:
        print("   no login form; is the client's redirect URI correct?")
        return 2

    step = session.post(action, data={"username": args.username},
                        timeout=TIMEOUT, allow_redirects=False)
    relax_cookies(session)
    has_password = 'type="password"' in (step.text or "")
    print(f"2. submit {args.username!r}")
    print(f"   status={step.status_code} password_form={has_password}")

    location = step.headers.get("Location", "") or ""
    if not location and not has_password:
        location = broker_link(step.text) or ""

    provider_login = None
    hops = 0
    while location and hops < 6:
        if args.redirect_uri and location.startswith(args.redirect_uri):
            break
        target = absolute(location, base)
        hop = session.get(target, timeout=TIMEOUT, allow_redirects=False)
        relax_cookies(session)
        hops += 1
        nxt = hop.headers.get("Location", "") or ""
        if hop.status_code == 200 and 'type="password"' in (hop.text or ""):
            provider_login = hop
            print(f"3. reached a provider login page   -> {target[:90]}")
            break
        if not nxt:
            nxt = broker_link(hop.text) or ""
        if "/protocol/openid-connect/auth" in target and "realms" in target:
            print(f"   routed to provider: {target[:110]}")
        location = nxt

    if provider_login is not None:
        user = args.idp_username or args.username
        pw = args.idp_password or args.password
        if not pw:
            print("   provider asked for a password; pass --idp-password")
            return 2
        posted = session.post(form_action(provider_login.text),
                              data={"username": user, "password": pw, "credentialId": ""},
                              timeout=TIMEOUT, allow_redirects=False)
        relax_cookies(session)
        location = posted.headers.get("Location", "") or ""
        print(f"4. authenticated at provider       -> {posted.status_code}")
    elif has_password:
        if not args.password:
            print("   a password form was shown; pass --password to continue")
            return 0
        posted = session.post(form_action(step.text),
                              data={"username": args.username,
                                    "password": args.password, "credentialId": ""},
                              timeout=TIMEOUT, allow_redirects=False)
        relax_cookies(session)
        location = posted.headers.get("Location", "") or ""
        print(f"3. submitted password              -> {posted.status_code}")

    for _ in range(8):
        if not location or location.startswith(args.redirect_uri):
            break
        hop = session.get(absolute(location, base), timeout=TIMEOUT, allow_redirects=False)
        relax_cookies(session)
        location = hop.headers.get("Location", "") or ""

    if location.startswith(args.redirect_uri):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)
        print(f"5. back at the application         -> code={'code' in query} "
              f"state={query.get('state')}")
        return 0 if "code" in query else 1

    print(f"   login did not reach {args.redirect_uri}; stopped at {location[:110]!r}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
