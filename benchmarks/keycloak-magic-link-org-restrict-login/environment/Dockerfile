# Intentionally a single FROM: this task runs from a PREBUILT image so that running
# the benchmark never rebuilds a ~550MB Keycloak environment.
#
# `sandbox.docker_image` in ../task.md is what actually selects the runtime image, and
# with it set bench skips the docker build step entirely
# (benchflow/sandbox/docker.py::_validate_definition returns early). This file exists
# only because `bench tasks check` still validates the presence of
# environment/Dockerfile — the validator is stricter than the runtime. Keeping it a
# bare FROM means even if something does build it, there are no layers to execute.
#
# The real recipe — base images, the atomic-auth-flows jar, the realm fixture, the
# mail-capture server, the entrypoint, and the several non-obvious Wolfi/BusyBox and
# email-SPI workarounds — lives in ../image/, together with rebuild/publish steps.
# Change things there, rebuild, push, and this task picks it up with no edit here.
FROM quay.io/phasetwo/skillsbench-keycloak-magic-link-org-restrict-login:latest
