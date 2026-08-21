# Environment image for `keycloak-magic-link-org-restrict-login`

This directory is **not part of the test**. It is the recipe that produces the prebuilt
image the task references, so running the benchmark never rebuilds a ~550MB Keycloak image.

The task declares the image in `../task.md`:

```yaml
sandbox:
  docker_image: quay.io/phasetwo/skillsbench-keycloak-magic-link-org-restrict-login:latest
```

With `docker_image` set, bench references that image directly and skips the docker build step
entirely — `benchflow/sandbox/docker.py::_validate_definition` returns early, so no
`environment/Dockerfile` is required. Only `../environment/docker-compose.yaml` (which supplies
`privileged: true`, needed because Docker Desktop doesn't grant `NET_ADMIN` for bench's egress
firewall) and `../environment/skills/` (the standalone benchmark skills, referenced by path at run
time) stay on the test side.

## Rebuilding and publishing

```bash
IMG=quay.io/phasetwo/skillsbench-keycloak-magic-link-org-restrict-login:latest
docker build -t "$IMG" .
docker push "$IMG"          # requires `docker login quay.io`
```

Rebuild when any of the files here change — the realm fixture, the credentials, the
mail-capture server, the deployment-token proxy, the entrypoint/readiness scripts, or the
bundled `keycloak-atomic-auth-flows.jar`.

## What the image contains, and why

- **`quay.io/phasetwo/phasetwo-keycloak`** as the base (pinned by digest): already bundles both
  extensions this task needs as real Maven dependencies of `phasetwo-module` —
  `keycloak-orgs` (organizations, membership, `ext-select-org`) and `keycloak-magic-link`
  (`ext-magic-form`, `ext-auth-username-auth-note`, action-token handling). Plain upstream
  Keycloak has neither. Keycloak's *native* Organizations feature is deliberately never enabled.
- **`773532640636.dkr.ecr.us-west-2.amazonaws.com/mcp/staging:latest`** for the MCP server, tracked by tag rather than
  digest on purpose: a digest pin previously held this task on a build that predated several tool
  fixes, so the benchmark measured a server nobody shipped any more. The tradeoff is that a
  rebuild can change behavior without this task changing.
- **`keycloak-atomic-auth-flows.jar`**, required (not a convenience): Keycloak's own
  `partialImport` endpoint has no handler for authentication flows and silently ignores them
  (200 OK, `added: 0`, nothing created), so this extension's `/authentication-flow/import` is the
  only way to author the flow short of a long manual create/add-execution/set-requirement
  sequence.
- **`findutils`** and **`util-linux-bins`**, both non-obvious: this Wolfi base ships BusyBox
  `find` (no `-printf`, which breaks bench's skill-deployment step) and a BusyBox `setpriv`
  symlink without `--reuid` (which makes bench fall back to `su -l`, a login shell that resets
  the environment and drops `ANTHROPIC_API_KEY`, surfacing only as an opaque auth error).
- **`KC_SPI_EMAIL_TEMPLATE_PROVIDER` / `..._ENABLED`**: without these, `keycloak-magic-link`'s
  send path throws an NPE (`EmailTemplateProvider.setRealm` on a null provider) and no magic-link
  email is ever delivered.
