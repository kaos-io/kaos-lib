# Troubleshooting `dev`, `step run` and `build`

`kaosctl build` translates the errors a container engine prints into a message and a fix. The table is the same one the
command uses. Docker, Podman, Colima and Rancher Desktop are covered.

| You see | What it means | Do |
|---|---|---|
| `No usable container engine was found` | Neither `docker` nor `podman` is installed. | Follow the message for your system, then run `kaosctl build` again. [What it prints](build.md#when-no-engine-is-found) |
| `The container engine is installed but not running.` | The engine's background service is stopped. | Docker Desktop: open the app. Colima: `colima start`. Podman on macOS or Windows: `podman machine start`. Linux: `sudo systemctl start docker`. |
| `Your user is not allowed to use the container engine.` | You cannot open the engine's socket. | Linux: `sudo usermod -aG docker $USER`, then log out and in; or use rootless Podman. |
| `The disk is full.` | Not enough space for the image layers (the check wants 5 GB). | `docker system prune` or `podman system prune`; on Docker Desktop, Colima or Podman machine, enlarge the virtual disk. |
| `The build cannot reach the package index or a registry.` | No network, a proxy, or a company certificate. | Check the network. Behind a proxy set `HTTP_PROXY`, `HTTPS_PROXY` and `NO_PROXY` for the engine (Docker: `~/.docker/config.json` `proxies`; Podman: `containers.conf`), and add your company's certificate to the engine if it inspects traffic. |
| `The engine cannot pull a base image` | The registry wants you to sign in, or the image does not exist. | `docker login <registry>` or `podman login <registry>`; or change `FROM` to an image you can pull. |
| `The image's CPU architecture does not match this machine.` | An `amd64` image on an `arm64` machine (or the reverse) without emulation. | Docker Desktop and Colima include emulation. Colima on Apple silicon: `colima start --vm-type vz --vz-rosetta`. Linux: install `qemu-user-static` and `binfmt-support`. Or `kaosctl build --arch arm64` for a project built for arm64. |
| `The engine's layer cache is broken.` | A damaged cached layer. | `docker builder prune` or `podman system prune --all`, then build again. |

If the engine's own message is not in the table, the last lines of its output are printed. The Dockerfile doctor
([L-D rules](build.md#the-dockerfile-doctor)) or `kaosctl lint` may point at the cause.

## By system

**Linux.** Docker Engine needs your user in the `docker` group (log out and in after adding it). Podman runs without a
daemon and without root. In WSL2, install the engine inside the Linux distribution, not in Windows.

**macOS.** Docker has no engine of its own on a Mac: Colima, Podman (`podman machine`) or Docker Desktop each run a small
Linux virtual machine. `colima status` or `podman machine list` shows whether it is running. Building the platform's
`amd64` images on an Apple silicon Mac is emulated and several times slower; Colima's `--vz-rosetta` makes it faster. The free
disk space `kaosctl` shows may be the Mac's, not the virtual machine's.

**Windows.** The supported route is WSL2: install it (`wsl --install` in an administrator PowerShell, then restart), install
Docker Engine inside the Linux distribution and run `kaosctl` there too. Podman Desktop also works. Without administrator
rights, with WSL disabled by your organisation, or without virtualisation, ask your IT team: `kaosctl` cannot install or
enable anything for you.

## `kaosctl dev`

| You see | Do |
|---|---|
| `uv ... was not found, so pip is used` | Only a note: `pip` is slower, with the same result. To get uv: <https://docs.astral.sh/uv/getting-started/installation/>. |
| `Python 3.11 (the version of the step's image) was not found on this machine` | The environment uses your Python, which may differ from the image's. Install the version named (<https://www.python.org/downloads/>), run `kaosctl dev` again. |
| `model-training: skipped, its dependencies are large` | By design; `kaosctl dev --step model-training` sets it up. |
| `No matching distribution found for kaos-lib...` | The spec is not on the index. Pass the version your project uses: `--kaos-lib "kaos-lib[zitadel]==<version>"` (see [Install](install.md)). |
| `<file>: file not found next to the Dockerfile` | The Dockerfile installs from a file that is not in the step's folder. Fix the path or the `COPY`. |

## `kaosctl step run`

| You see | Do |
|---|---|
| `this step reads MLFLOW_TRACKING_URI, which only the platform sets` | Expected on a laptop. The step runs without it and may stop with its own error; give it a fallback or a stub. |
| `composing the parameters failed` | A bad `--set` override, or a config error: the message is the composer's own. `--params-file` skips composing. |
| `this repository has no kubecore/compose.py` | Pass `--params-file FILE`. |
| `input --x: empty ({})` | Run the step that produces `x` first, or pass `--input x=<json>`. |
