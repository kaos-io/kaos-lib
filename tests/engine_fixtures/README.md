# Recorded engine outputs

One text file per engine and cause: `<engine>/<key>.txt` (or `<key>__<variant>.txt`). `tests/test_studio_engine_errors.py`
checks that each file translates to the cause in its name (PRD-CONSOLE-1682 AC-41, section 7.3).

Captured live on a Fedora 44 workstation (Docker Engine 29.7.2, Podman 5.8.4), 2026-11-09:
`docker/daemon_not_running`, `docker/network` (a build through a refused proxy), `docker/registry_auth` (a private image
on ghcr.io), `docker/exec_format` (an arm64 image on an amd64 host without emulation), and the same four for `podman/`.

Written from the engines' published messages, because they cannot be produced safely here (a full disk, a corrupt cache,
a socket owned by another group, macOS Colima): `docker/permission_denied_socket*`, `docker/no_space`, `docker/cache_corrupt`,
`docker/registry_auth__pull_denied`, `podman/permission_denied_socket`, `podman/no_space`, and everything in `colima/`.
Replace them with real captures from a Mac when one is available (OQ-22).
