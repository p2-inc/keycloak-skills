<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# Google Workspace — SAML console walkthrough

Verified against Phase Two's [idp-wizard](https://github.com/p2-inc/idp-wizard)
(`Wizards/Providers/Google`). **This is Google Workspace SAML — a company's own Workspace tenant
acting as an enterprise SAML IdP.** It is not the `google` social-login button (the confirmation
screen there literally says "Google Workplace SAML"); a plain "log in with Google" request belongs
in `admin:social-login` instead.

## Steps, in order

1. **Google Admin console** → Apps → **Web and Mobile Apps** → **Add App** → **Add custom SAML
   app**. Enter an app name (and optional icon) → Continue.
2. Download the **IdP metadata file** Google offers on the next screen.
3. Call `createSamlIdp` with the explicit fallback fields read out of that file (Google hands back a
   file, not a URL, so `metadataUrl` doesn't apply directly) → Continue in the Google wizard.
4. Submit Keycloak's **ACS URL** and **Entity ID** into Google's "Service provider details" fields →
   Continue.
5. Configure attribute mapping in Google (see below) → Finish.
6. In the app's **User Access** section, turn the service **ON** for the correct organizational
   units, Save.

## Attribute mapping (Keycloak side)

| Google attribute | Keycloak `userAttribute` |
|---|---|
| Primary email | `email` |
| First name | `firstName` |
| Last name | `lastName` |

## Gotchas

- Google explicitly warns the **User Access** (org-unit) change can take **up to 24 hours** to
  propagate — a "not working yet" report right after setup may just be propagation delay, not a
  misconfiguration. Set that expectation with the developer up front.
