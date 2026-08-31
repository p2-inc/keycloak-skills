# Copyright 2026 Phase Two, Inc.
# SPDX-License-Identifier: Apache-2.0

"""A mock Okta / Entra ID SAML identity provider that fires "portal tiles" at Keycloak.

There is no real Okta or Entra tenant, and the sandbox is `no-network`. So instead of a
vendor (or a second Keycloak realm) producing the unsolicited SAML response, this module
hand-builds one and POSTs it at the broker's IdP-initiated endpoint:

    POST {base}/realms/{realm}/broker/{alias}/endpoint/clients/{urlName}
    SAMLResponse=<base64 of the RAW XML>      # POST binding: base64 only, NOT deflated
    RelayState=<optional>

What makes the response *unsolicited* (i.e. a tile click rather than a reply to an
AuthnRequest the app started) is the absence of `InResponseTo`.

**Signatures are deliberately absent.** Both fixture identity providers are configured
with `validateSignature=false` and `wantAssertionsSigned=false`, so Keycloak accepts an
unsigned assertion. That is a sanctioned sandbox simplification, documented in `task.md`
and `verifier/rubrics/verifier.md`, not an oversight: nothing this task measures (which
client the tile lands in, and in what delivery shape) depends on signature validation.

The two vendor flavours differ the way the real ones do:

  okta   NameID format emailAddress, plain attribute names (email/firstName/lastName)
  entra  NameID format persistent (an opaque object id), attribute names in the
         http://schemas.xmlsoap.org/ws/2005/05/identity/claims/... namespaces

Both flavours must work, which is the point: the wiring is on the *client*, so it cannot
be tied to one IdP alias.

NOTE: this file is duplicated byte-for-byte at `oracle/mock_idp.py`. The oracle needs it
for its own self-check and `/verifier` is not mounted during the solve phase; it is
deliberately NOT baked into the container image, because that would hand the agent the
broker endpoint URL for free and spoil the no-skill arm.
"""

import base64
import datetime
import re
import urllib.parse
import uuid
import zlib

import requests

TIMEOUT = 30

VENDORS = {
    "okta": {
        "alias": "okta-sso",
        "idp_entity_id": "https://mock-okta.example/saml/metadata",
        "name_id_format": "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
        # Okta ships plain, un-namespaced attribute names by default.
        "attributes": [
            ("email", "urn:oasis:names:tc:SAML:2.0:attrname-format:unspecified",
             "taylor@acme.example"),
            ("firstName", "urn:oasis:names:tc:SAML:2.0:attrname-format:unspecified",
             "Taylor"),
            ("lastName", "urn:oasis:names:tc:SAML:2.0:attrname-format:unspecified",
             "Nguyen"),
        ],
        # Matches taylor's pre-seeded federatedIdentities entry for okta-sso.
        "name_id": "taylor@acme.example",
    },
    "entra": {
        "alias": "entra-sso",
        "idp_entity_id": "https://sts.windows.net/mock-tenant-id/",
        "name_id_format": "urn:oasis:names:tc:SAML:2.0:nameid-format:persistent",
        # Entra ID emits the WS-* claim namespaces, not plain names.
        "attributes": [
            ("http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress",
             "urn:oasis:names:tc:SAML:2.0:attrname-format:uri", "taylor@acme.example"),
            ("http://schemas.xmlsoap.org/ws/2005/05/identity/claims/givenname",
             "urn:oasis:names:tc:SAML:2.0:attrname-format:uri", "Taylor"),
            ("http://schemas.xmlsoap.org/ws/2005/05/identity/claims/surname",
             "urn:oasis:names:tc:SAML:2.0:attrname-format:uri", "Nguyen"),
            ("http://schemas.microsoft.com/identity/claims/objectidentifier",
             "urn:oasis:names:tc:SAML:2.0:attrname-format:uri",
             "AAAAAAAAAAAAAAAAAAAAAHRheWxvcm1vY2tlbnRyYW9pZA"),
        ],
        # Matches taylor's pre-seeded federatedIdentities entry for entra-sso.
        "name_id": "AAAAAAAAAAAAAAAAAAAAAHRheWxvcm1vY2tlbnRyYW9pZA",
    },
}


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _esc(value):
    return (str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def tile_endpoint(base, realm, alias, url_name):
    """The URL a vendor console would be given as its ACS / Reply URL."""
    return f"{base.rstrip('/')}/realms/{realm}/broker/{alias}/endpoint/clients/{url_name}"


def build_saml_response(vendor, destination, audience, name_id=None):
    """An unsolicited (no InResponseTo), unsigned SAML Response, as raw XML.

    `destination` must be the exact URL it will be POSTed to, and `audience` the broker's
    SP entity ID ({base}/realms/{realm}) - Keycloak checks both.
    """
    v = VENDORS[vendor]
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    not_before = _iso(now - datetime.timedelta(minutes=5))
    not_on_or_after = _iso(now + datetime.timedelta(minutes=10))
    issue_instant = _iso(now)
    resp_id = "_" + uuid.uuid4().hex
    assertion_id = "_" + uuid.uuid4().hex
    session_index = "_" + uuid.uuid4().hex
    subject = name_id if name_id is not None else v["name_id"]

    attrs = "".join(
        f'<saml:Attribute Name="{_esc(n)}" NameFormat="{_esc(fmt)}">'
        f'<saml:AttributeValue xmlns:xs="http://www.w3.org/2001/XMLSchema"'
        f' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
        f' xsi:type="xs:string">{_esc(val)}</saml:AttributeValue>'
        f"</saml:Attribute>"
        for n, fmt, val in v["attributes"]
    )

    return (
        '<samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol"'
        ' xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion"'
        f' ID="{resp_id}" Version="2.0" IssueInstant="{issue_instant}"'
        f' Destination="{_esc(destination)}">'
        f'<saml:Issuer>{_esc(v["idp_entity_id"])}</saml:Issuer>'
        "<samlp:Status>"
        '<samlp:StatusCode Value="urn:oasis:names:tc:SAML:2.0:status:Success"/>'
        "</samlp:Status>"
        f'<saml:Assertion ID="{assertion_id}" Version="2.0" IssueInstant="{issue_instant}">'
        f'<saml:Issuer>{_esc(v["idp_entity_id"])}</saml:Issuer>'
        "<saml:Subject>"
        f'<saml:NameID Format="{_esc(v["name_id_format"])}">{_esc(subject)}</saml:NameID>'
        '<saml:SubjectConfirmation Method="urn:oasis:names:tc:SAML:2.0:cm:bearer">'
        f'<saml:SubjectConfirmationData NotOnOrAfter="{not_on_or_after}"'
        f' Recipient="{_esc(destination)}"/>'
        "</saml:SubjectConfirmation>"
        "</saml:Subject>"
        f'<saml:Conditions NotBefore="{not_before}" NotOnOrAfter="{not_on_or_after}">'
        f"<saml:AudienceRestriction><saml:Audience>{_esc(audience)}</saml:Audience>"
        "</saml:AudienceRestriction>"
        "</saml:Conditions>"
        f'<saml:AuthnStatement AuthnInstant="{issue_instant}" SessionIndex="{session_index}">'
        "<saml:AuthnContext><saml:AuthnContextClassRef>"
        "urn:oasis:names:tc:SAML:2.0:ac:classes:PasswordProtectedTransport"
        "</saml:AuthnContextClassRef></saml:AuthnContext>"
        "</saml:AuthnStatement>"
        f"<saml:AttributeStatement>{attrs}</saml:AttributeStatement>"
        "</saml:Assertion>"
        "</samlp:Response>"
    )


class Delivery:
    """Where and how the browser was finally sent, after the tile POST.

    kind is one of:
      "redirect" - a 302/303 whose Location left Keycloak (REDIRECT binding, a GET)
      "post"     - a 200 HTML auto-POST form targeting a non-Keycloak URL (POST binding)
      "error"    - Keycloak rendered an error page and never delivered anything
      "stuck"    - the chain ended inside Keycloak without delivering (e.g. a login form)
    """

    def __init__(self, kind, target=None, status=None, body="", saml_response=None,
                 relay_state=None, hops=None):
        self.kind = kind
        self.target = target
        self.status = status
        self.body = body or ""
        self.saml_response = saml_response
        self.relay_state = relay_state
        self.hops = hops or []

    def __repr__(self):
        return (f"Delivery(kind={self.kind!r}, target={self.target!r}, "
                f"status={self.status!r}, hops={len(self.hops)})")

    def summary(self, limit=400):
        text = re.sub(r"<[^>]+>", " ", self.body)
        text = re.sub(r"\s+", " ", text).strip()
        return (f"kind={self.kind} status={self.status} target={self.target!r} "
                f"hops={self.hops} body={text[:limit]!r}")


def delivered_audiences(delivery):
    """The <saml:Audience> values in the response Keycloak DELIVERED to the app.

    Keycloak puts the target client's clientId there, so this is the decisive answer to
    "which client did the user actually land in" - independent of the URL. The redirect
    binding deflates before base64; the POST binding does not.
    """
    if not delivery.saml_response:
        return []
    raw = base64.b64decode(delivery.saml_response)
    try:
        xml = zlib.decompress(raw, -15).decode("utf-8")
    except zlib.error:
        xml = raw.decode("utf-8", "replace")
    return re.findall(r"<(?:\w+:)?Audience>([^<]*)</(?:\w+:)?Audience>", xml)


def _relax(session):
    """Keycloak marks AUTH_SESSION_ID / KC_RESTART Secure; a browser sends them over
    http://localhost anyway (loopback is a secure context) but `requests` will not, so
    letting requests keep them Secure silently loses the session mid-chain."""
    for cookie in session.cookies:
        cookie.secure = False


_FORM_RE = re.compile(r"<form[^>]*\baction=[\"']([^\"']+)[\"']", re.I)
_INPUT_RE = re.compile(
    r"<input[^>]*\bname=[\"']([^\"']+)[\"'][^>]*\bvalue=[\"']([^\"']*)[\"']", re.I)


def _auto_post_form(html):
    """(action, {field: value}) of an auto-POST binding page, or None."""
    m = _FORM_RE.search(html or "")
    if not m:
        return None
    action = m.group(1).replace("&amp;", "&")
    fields = {name: value.replace("&amp;", "&") for name, value in _INPUT_RE.findall(html)}
    if "SAMLResponse" not in fields:
        return None
    return action, fields


def deliver_tile(base, realm, url_name, vendor, relay_state=None, name_id=None,
                 alias=None, max_hops=15):
    """Fire one portal tile at Keycloak and report how the browser was delivered.

    Follows Keycloak's internal redirect chain but deliberately stops before requesting
    anything off-host: the two apps (:9999 and :9998) are not listening in the sandbox,
    and where the browser was sent is exactly what is being measured.
    """
    base = base.rstrip("/")
    v = VENDORS[vendor]
    alias = alias or v["alias"]
    endpoint = tile_endpoint(base, realm, alias, url_name)
    audience = f"{base}/realms/{realm}"

    xml = build_saml_response(vendor, endpoint, audience, name_id=name_id)
    form = {"SAMLResponse": base64.b64encode(xml.encode("utf-8")).decode("ascii")}
    if relay_state is not None:
        form["RelayState"] = relay_state

    keycloak_host = urllib.parse.urlparse(base).netloc
    session = requests.Session()
    hops = [f"POST {endpoint}"]
    resp = session.post(endpoint, data=form, timeout=TIMEOUT, allow_redirects=False)
    _relax(session)

    for _ in range(max_hops):
        location = resp.headers.get("Location", "")
        if location:
            absolute = location if location.startswith("http") else f"{base}{location}"
            if urllib.parse.urlparse(absolute).netloc != keycloak_host:
                query = urllib.parse.parse_qs(urllib.parse.urlparse(absolute).query)
                hops.append(f"{resp.status_code} -> {absolute}")
                return Delivery(
                    "redirect", target=absolute, status=resp.status_code,
                    body=resp.text,
                    saml_response=(query.get("SAMLResponse") or [None])[0],
                    relay_state=(query.get("RelayState") or [None])[0],
                    hops=hops)
            hops.append(f"{resp.status_code} -> {absolute}")
            resp = session.get(absolute, timeout=TIMEOUT, allow_redirects=False)
            _relax(session)
            continue

        posted = _auto_post_form(resp.text)
        if posted:
            action, fields = posted
            if urllib.parse.urlparse(action).netloc != keycloak_host:
                hops.append(f"{resp.status_code} auto-POST form -> {action}")
                return Delivery(
                    "post", target=action, status=resp.status_code, body=resp.text,
                    saml_response=fields.get("SAMLResponse"),
                    relay_state=fields.get("RelayState"), hops=hops)

        lowered = (resp.text or "").lower()
        kind = "error" if ("kc-error-message" in lowered or "we are sorry" in lowered
                           or "error" in lowered[:2000]) else "stuck"
        hops.append(f"{resp.status_code} (no further redirect)")
        return Delivery(kind, target=resp.url, status=resp.status_code, body=resp.text,
                        hops=hops)

    return Delivery("stuck", target=resp.url, status=resp.status_code, body=resp.text,
                    hops=hops)
