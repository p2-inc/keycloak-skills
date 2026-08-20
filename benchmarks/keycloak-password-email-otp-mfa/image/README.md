# Environment image notes for `keycloak-password-email-otp-mfa`

**Current mode: the image is BUILT IN THE TEST.** `environment/Dockerfile` is the real recipe and
bench builds it on each run (Docker layer cache makes repeat runs fast). There is no
`sandbox.docker_image` in `../task.md`, so nothing is pulled from a registry.

This directory now holds only these notes. The build inputs live in `../environment/` next to the
Dockerfile.

## Why it is this way (and how to switch back)

The task previously used a prebuilt image (`sandbox.docker_image`) so that running the benchmark
never rebuilt a ~1.4GB Keycloak image. That works for `--skill-mode no-skill`, but it **broke
`--skill-mode with-skill`**: the image was built locally and never pushed, bench's cache reclaim
removed it between runs, and compose then tried to pull a nonexistent
`quay.io/phasetwo/skillsbench-keycloak-password-email-otp-mfa:latest` — surfacing only as an opaque
"Docker compose command failed". Building in the test has no registry dependency and works for
both arms, which is what the other benchmarks in this repo do.

To switch back to a published image once one is actually pushed:

```bash
IMG=quay.io/phasetwo/skillsbench-keycloak-password-email-otp-mfa:latest
docker build -t "$IMG" ../environment      # the Dockerfile lives there now
docker push "$IMG"                          # requires `docker login quay.io`
```

then add to `../task.md` under `sandbox:`:

```yaml
  docker_image: quay.io/phasetwo/skillsbench-keycloak-password-email-otp-mfa:latest
```

With `docker_image` set, bench skips the build entirely
(`benchflow/sandbox/docker.py::_validate_definition` returns early). Keep a one-line
`FROM <that image>` as `environment/Dockerfile` — `bench tasks check` still validates its
presence even though the runtime does not need it. **Only do this once the image is genuinely
pushed**, or the with-skill arm breaks again as described above.

## Environment gotchas worth keeping (they cost real debugging time)

- **`quay.io/phasetwo/phasetwo-keycloak` base (digest-pinned)** already bundles
  `keycloak-magic-link` (`ext-email-otp`, `ext-auth-username-auth-note`, `ext-magic-form`, email
  templates) and `keycloak-orgs`. Plain upstream Keycloak has neither, and there is no stock
  equivalent to `ext-email-otp` (Keycloak's own OTP is TOTP/HOTP against an authenticator app).
- **`keycloak-atomic-auth-flows.jar`** is required, not a convenience: Keycloak's own
  `partialImport` has no handler for authentication flows and silently ignores them (200 OK,
  `added: 0`, nothing created).
- **`findutils` + `util-linux-bins`**: the Wolfi base ships BusyBox `find` (no `-printf`, which
  breaks bench's skill deployment with `experiment_fidelity/skill_deployment_missing`) and a
  BusyBox `setpriv` without `--reuid` (which makes bench fall back to `su -l`, a login shell that
  resets the environment and drops `ANTHROPIC_API_KEY`, surfacing only as an opaque auth error).
- **`KC_SPI_EMAIL_TEMPLATE_PROVIDER` / `..._ENABLED`**: without these the magic-link family's send
  path throws an NPE (`EmailTemplateProvider.setRealm` on a null provider) and no mail is ever
  delivered.
- **`privileged: true`** in `environment/docker-compose.yaml`: Docker Desktop does not grant
  `NET_ADMIN`, so bench's egress firewall for no-network tasks fails without it.

## The mail-capture format trap

`mail_capture_server.py` writes one **JSON** document per message, not a raw `.eml`, and that JSON
carries a float `received_at` whose fractional part is six digits. A naive `\b\d{6}\b` regex
over the whole file returns the timestamp instead of the one-time code — this actually happened
here and produced a verifier that passed while the oracle failed. Parse the JSON and read
`body_plain`/`body_html`; both oracles use a shared `extract_code()` that does.
