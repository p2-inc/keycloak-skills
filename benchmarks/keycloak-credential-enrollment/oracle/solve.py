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
  4. defaultAction covers users created afterwards; it is NOT retroactive, so
     it is not a substitute for either step above.
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

    # --- 4. Marcus: no credential exists, so nothing can be "added to his next
    #        login". The action-token email IS his authentication. Note we never
    #        set a password for him - that shortcut is what the task forbids. ---
    mid = user_id("marcus")
    q = urllib.parse.urlencode({
        "client_id": "acme-portal",
        "redirect_uri": "http://localhost:9999/callback",
    })
    r = S.put(
        f"{BASE}/admin/realms/{REALM}/users/{mid}/execute-actions-email?{q}",
        headers=h, json=[ACTION], timeout=60,
    )
    r.raise_for_status()
    print(f"enrollment email queued for marcus (HTTP {r.status_code})")

    print(json.dumps({"ok": True, "action": ACTION}, indent=2))


if __name__ == "__main__":
    sys.exit(main())
