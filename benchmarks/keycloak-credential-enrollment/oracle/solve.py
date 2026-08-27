#!/usr/bin/env python3
"""Reference solution for keycloak-credential-enrollment.

Drives the same Admin REST calls a human (or an agent following the
`admin:credential-enrollment` reference) would use. Deliberately plain REST so
the oracle costs nothing to run and does not depend on the MCP server.

The ordering matters and is the point of the task:
  1. CONFIGURE_TOTP ships registered-but-DISABLED. Until it is enabled, both
     enrollment mechanisms are accepted by the API and silently never fire.
  2. Priya can already authenticate -> a required action on her user reaches
     her at next login. No mail involved.
  3. Marcus has no credential at all -> only an action-token email can reach
     him, which needs realm SMTP configured first.
  4. An action-token link authenticates whoever opens it, so it goes only to a
     VERIFIED address. Keycloak does not enforce this - it returns 204 and
     delivers the mail to an unverified address - so the caller must.
  5. defaultAction covers users created afterwards; it is NOT retroactive, so
     it is not a substitute for any step above.
"""
import json
import sys
import urllib.parse

import requests

BASE = "http://localhost:8080/auth"
REALM = "acme"
ACTION = "CONFIGURE_TOTP"
S = requests.Session()


def admin_token():
    r = S.post(
        f"{BASE}/realms/master/protocol/openid-connect/token",
        data={
            "client_id": "admin-cli",
            "grant_type": "password",
            "username": "admin",
            "password": "admin_change_me",
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def main():
    h = {"Authorization": f"Bearer {admin_token()}", "Content-Type": "application/json"}

    # --- 1. Make the action live. Read-then-merge: this PUT replaces the rep. ---
    actions = S.get(f"{BASE}/admin/realms/{REALM}/authentication/required-actions",
                    headers=h, timeout=30).json()
    totp = next((a for a in actions if a.get("alias") == ACTION), None)
    if totp is None:
        # Not registered at all -> register first, then re-read.
        S.post(f"{BASE}/admin/realms/{REALM}/authentication/register-required-action",
               headers=h, json={"providerId": ACTION, "name": ACTION}, timeout=30)
        actions = S.get(f"{BASE}/admin/realms/{REALM}/authentication/required-actions",
                        headers=h, timeout=30).json()
        totp = next(a for a in actions if a.get("alias") == ACTION)

    totp["enabled"] = True
    totp["defaultAction"] = True          # requirement 3: applies to NEW users only
    r = S.put(f"{BASE}/admin/realms/{REALM}/authentication/required-actions/{ACTION}",
              headers=h, json=totp, timeout=30)
    r.raise_for_status()
    print(f"enabled + defaultAction on {ACTION}")

    # --- 2. Realm SMTP, needed only by the email variant. ---
    realm = S.get(f"{BASE}/admin/realms/{REALM}", headers=h, timeout=30).json()
    realm["smtpServer"] = {
        "host": "localhost",
        "port": "1025",
        "from": "noreply@acme.example",
        "fromDisplayName": "Acme Portal",
        "ssl": "false",
        "starttls": "false",
        "auth": "false",
    }
    r = S.put(f"{BASE}/admin/realms/{REALM}", headers=h, json=realm, timeout=30)
    r.raise_for_status()
    print("smtp configured")

    def user_id(username):
        q = urllib.parse.urlencode({"username": username, "exact": "true"})
        found = S.get(f"{BASE}/admin/realms/{REALM}/users?{q}", headers=h, timeout=30).json()
        return found[0]["id"]

    # --- 3. Priya: required action on the user. She has a password, so this
    #        reaches her at next login. No mail, no SMTP dependency. ---
    pid = user_id("priya")
    priya = S.get(f"{BASE}/admin/realms/{REALM}/users/{pid}", headers=h, timeout=30).json()
    priya["requiredActions"] = sorted(set(priya.get("requiredActions") or []) | {ACTION})
    r = S.put(f"{BASE}/admin/realms/{REALM}/users/{pid}", headers=h, json=priya, timeout=30)
    r.raise_for_status()
    print(f"priya requiredActions -> {priya['requiredActions']}")

    # --- 4. Everyone else: decide per user from FACTS, not from names. A user
    #        with no credential cannot be reached by step 3 at all; a user whose
    #        address is unverified must not be mailed an action token, because
    #        that token authenticates whoever opens it. We never set a password
    #        for anyone - that shortcut is what the task forbids. ---
    q = urllib.parse.urlencode({
        "client_id": "acme-portal",
        "redirect_uri": "http://localhost:9999/callback",
    })
    emailed, skipped = [], []
    for username in ("marcus", "dana"):
        uid = user_id(username)
        user = S.get(f"{BASE}/admin/realms/{REALM}/users/{uid}", headers=h, timeout=30).json()

        # The dedicated credentials endpoint - a user SEARCH never populates
        # `credentials`, so deciding this from search results says "none" for
        # everyone, including users who plainly have a password.
        creds = S.get(f"{BASE}/admin/realms/{REALM}/users/{uid}/credentials",
                      headers=h, timeout=30).json()
        has_credential = bool(creds)

        if not user.get("emailVerified"):
            skipped.append((username, "email not verified"))
            continue
        if has_credential:
            # Could be reached by a required action instead; no mail needed.
            skipped.append((username, "already holds a credential"))
            continue

        r = S.put(
            f"{BASE}/admin/realms/{REALM}/users/{uid}/execute-actions-email?{q}",
            headers=h, json=[ACTION], timeout=60,
        )
        r.raise_for_status()
        emailed.append(username)

    print(f"enrollment email sent to: {emailed}")
    for username, why in skipped:
        print(f"skipped {username}: {why}")

    print(json.dumps({"ok": True, "action": ACTION,
                      "emailed": emailed,
                      "skipped": {u: w for u, w in skipped}}, indent=2))


if __name__ == "__main__":
    sys.exit(main())
