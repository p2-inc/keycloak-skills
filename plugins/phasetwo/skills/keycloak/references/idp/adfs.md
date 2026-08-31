<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# ADFS — SAML console walkthrough

Verified against Phase Two's [idp-wizard](https://github.com/p2-inc/idp-wizard)
(`Wizards/Providers/ADFS`). Unlike most vendors in this family, ADFS's own metadata comes first —
its federation metadata URL is what gets fetched into Keycloak *before* ADFS needs anything back.

## Steps, in order

1. In the ADFS management console, find the federation metadata path under **AD FS → Service →
   Endpoints**, and combine it with the server's FQDN to get ADFS's federation metadata URL.
2. Call `createSamlIdp` with that URL as `metadataUrl` — Keycloak parses ADFS's entity ID, SSO URL,
   and certificate from it.
3. In ADFS: right-click **Relying Party Trusts** → **Add Relying Party Trust** → choose
   **"Claims Aware"** → Start.
4. Choose **"Import data about the relying party published online or on a local network"** and
   supply a Display Name — this is where Keycloak's **SP metadata URL**
   (`{BASE}/realms/{REALM}/broker/{ALIAS}/endpoint/descriptor`) goes, as the "federation metadata
   address" ADFS fetches from.
5. Pick an **Access Control Policy** — "Permit everyone" is the most permissive; the wizard notes
   it's useful "while testing," not necessarily for production.
6. Finish, checking **"Configure claims issuance policy for this application"** on the way out.
7. In the Claims Issuance Policy editor, add two rules:
   - **"Transform an Incoming Claim"**, named "Name ID": Incoming claim type `UPN` → Outgoing claim
     type `Name ID`, Outgoing name ID format `Persistent Identifier`.
   - **"Send LDAP Attributes as Claims"**, named "Attributes", using the Active Directory attribute
     store.

## Attribute mapping (Keycloak side)

| ADFS LDAP attribute | Outgoing claim | Keycloak `userAttribute` |
|---|---|---|
| E-Mail-Addresses | E-Mail Address | `email` |
| Given-Name | Given Name | `firstName` |
| Surname | Surname | `lastName` |
| SAM-Account-Name | Subject Name | username |

## Gotchas

- "Permit everyone" is a testing-grade access policy — flag it to the developer as something to
  tighten before production.
- Order matters: Keycloak needs to already know about ADFS (step 2) before ADFS's Relying Party
  Trust wizard can point back at Keycloak's SP metadata descriptor (step 4).
