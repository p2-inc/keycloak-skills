#!/usr/bin/env python3

# Copyright 2026 Phase Two, Inc.
# SPDX-License-Identifier: Apache-2.0

"""A minimal SMTP capture server.

Realm SMTP settings point Keycloak's own mail sender at this process. Every
message Keycloak actually sends - the magic-link email included - is captured
here rather than delivered anywhere, and written to /var/mail-capture/ as one
JSON file per message so the oracle and verifier can read it without needing
any SMTP client of their own.

This is not a stand-in for a mail server: it accepts anything and asserts
nothing about deliverability. Its only job is to make the realm's outgoing
mail inspectable from inside the same container.
"""

import email
import json
import pathlib
import sys
import time

from aiosmtpd.controller import Controller
from aiosmtpd.smtp import SMTP as SMTPProtocol

CAPTURE_DIR = pathlib.Path("/var/mail-capture")
CAPTURE_DIR.mkdir(parents=True, exist_ok=True)


def _extract_bodies(msg):
    plain, html = None, None
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain" and plain is None:
                plain = part.get_payload(decode=True).decode(errors="replace")
            elif content_type == "text/html" and html is None:
                html = part.get_payload(decode=True).decode(errors="replace")
    else:
        payload = msg.get_payload(decode=True)
        if payload is not None:
            body = payload.decode(errors="replace")
            if msg.get_content_type() == "text/html":
                html = body
            else:
                plain = body
    return plain, html


class CaptureHandler:
    async def handle_DATA(self, server, session, envelope):
        msg = email.message_from_bytes(envelope.content)
        plain, html = _extract_bodies(msg)
        record = {
            "received_at": time.time(),
            "mail_from": envelope.mail_from,
            "rcpt_tos": envelope.rcpt_tos,
            "subject": msg.get("Subject", ""),
            "to_header": msg.get("To", ""),
            "body_plain": plain,
            "body_html": html,
        }
        # One file per recipient per message, timestamp-ordered, so a reader
        # can find "the most recent message to this address" without parsing
        # a shared log.
        for rcpt in envelope.rcpt_tos:
            safe = rcpt.replace("@", "-at-").replace("/", "_")
            path = CAPTURE_DIR / f"{int(time.time() * 1000)}-{safe}.json"
            path.write_text(json.dumps(record, indent=2))
        sys.stderr.write(
            f"captured mail: from={envelope.mail_from} to={envelope.rcpt_tos} "
            f"subject={record['subject']!r}\n"
        )
        return "250 Message accepted for delivery"


def main():
    controller = Controller(
        CaptureHandler(), hostname="0.0.0.0", port=1025, server_hostname="localhost"
    )
    controller.start()
    sys.stderr.write("mail capture server listening on :1025, writing to " f"{CAPTURE_DIR}\n")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        controller.stop()


if __name__ == "__main__":
    main()
