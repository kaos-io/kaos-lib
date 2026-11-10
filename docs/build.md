# Build a step image: `kaosctl build`

`kaosctl build [step]` builds a step's image on your machine, with a container engine you already have, so you see
whether it builds before you push. It checks the Dockerfile first, finds and verifies the engine, builds with the same inputs
as the platform's build, and tells you in plain words what went wrong when it does not work. The image stays on your
machine: nothing is pushed.

```bash
kaosctl build                 # every step with a Dockerfile
kaosctl build hello-world     # one step
```

!!! important "kaosctl installs nothing"
    `kaosctl` never installs a container engine, `uv`, or anything else, and never runs a package manager or an installer.
    When something is missing it says what, and gives you the official link and the exact command to run yourself.

## The steps of a build

1. **The Dockerfile doctor** reads each Dockerfile you are about to build (it never builds or runs anything) and reports
   the [L-D checks](#the-dockerfile-doctor). An error stops the build (exit code `2`); warnings and infos are shown and the
   build goes on. `kaosctl lint` and the pull request check report the same findings.
2. **Find an engine.** `docker` and `podman` on your `PATH`. Docker Engine, Docker Desktop, Colima and Rancher Desktop all
   answer to `docker`; Podman answers to `podman`. If both are there, `docker` is used; `--engine podman` chooses.
3. **Verify it.** The engine answers; a tiny test build works (it uses an empty base image, so it needs no network and
   leaves nothing behind); there are at least 5 GB free where it keeps images; and the architecture works: an Apple
   silicon Mac building the platform's `amd64` images needs emulation, and the command says the build will be slower.
4. **Build** with CI's inputs, for the platform's architecture, and print the image's local name.
5. **Explain failures**: a known engine error becomes a message and a fix ([troubleshooting](troubleshooting-build.md)).

## The same inputs as the platform's build

| Input | Locally |
|---|---|
| Dockerfile | `steps/<name>/Dockerfile` |
| Context | the step's folder; the repository root for `compose-and-validate` |
| `REGISTRY_URL` | `local` (the platform passes its registry); `--registry-url` changes it |
| `VERSION` | `local-<short commit>` (`local-nogit` outside a git repository) |
| `KAOS_LIB_PACKAGE` and the label `io.kaos.lib` | only for a Dockerfile that declares `ARG KAOS_LIB_PACKAGE`. Passed when you give `--kaos-lib` or `--context`; otherwise the Dockerfile's own default installs and the label names it |
| Architecture | `linux/amd64`; `--arch arm64` or `$KAOS_BUILD_ARCH` changes it for a project built for arm64 |
| Tag | `kaos-local/<app folder>:<step>-local-<short commit>`: visibly local, never a registry name |

The built image is proved equal to the platform's by these inputs and by the contract, not byte for byte: two builds of the
same commit by different builders do not produce identical digests. To see the exact command without building, use
`--dry-run`.

Try the image the way the platform starts it: `docker run --rm <tag> --params "$(cat .kaos/local/params.yaml)"`.

## The Dockerfile doctor

| Rule | Level | Finds |
|---|---|---|
| [L-D01 MissingKaosLibArg](lint/L-D01.md) | error | a step that uses kaos-lib but whose Dockerfile has no `ARG KAOS_LIB_PACKAGE` |
| [L-D02 KaosLibNotInstalled](lint/L-D02.md) | error | the step imports `kaos_lib` but nothing installs `${KAOS_LIB_PACKAGE}` |
| [L-D03 WrongArchitecture](lint/L-D03.md) | error | a `FROM --platform=` other than `linux/amd64` |
| [L-D04 CopyOutsideContext](lint/L-D04.md) | error | a `COPY` source that is absolute, above the context, or missing |
| [L-D05 StepContract](lint/L-D05.md) | error, warning | no `app/entry.py` (error); no `python -m app.entry` entrypoint (warning) |
| [L-D06 HugeLayers](lint/L-D06.md) | warning | `COPY . .`, baked-in data, `pip` without `--no-cache-dir`, `apt-get` without cleanup |
| [L-D07 RootUser](lint/L-D07.md) | info | the image runs as root (the platform does not require otherwise today) |
| [L-D08 NoCudaForGpuStep](lint/L-D08.md) | warning | a `gpu=True` step whose image shows no CUDA support, or whose plain base sets no NVIDIA driver path |

Each finding has the Dockerfile line, a fix and a page. A step without a Dockerfile is not judged.

## When no engine is found

`kaosctl build` prints what to install for your system and stops with exit code `1`. For example on Ubuntu:

```text
What to install (free): Docker Engine
  Official instructions: https://docs.docker.com/engine/install/
  Command to run yourself (Docker's own install script; read it first at https://get.docker.com):
      curl -fsSL https://get.docker.com -o get-docker.sh && sudo sh get-docker.sh
  Then let your user use it (log out and in afterwards):
      sudo usermod -aG docker $USER
...
kaosctl did not run any of these commands. After installing, run `kaosctl build` again.
```

| System | Free engine recommended | Official instructions |
|---|---|---|
| Linux | Docker Engine (alternative: Podman, from your distribution) | <https://docs.docker.com/engine/install/> |
| macOS | Colima (alternative: Podman) | <https://github.com/abiosoft/colima#installation> |
| Windows | Docker Engine inside WSL2 (alternative: Podman Desktop) | <https://learn.microsoft.com/windows/wsl/install> |

Docker Desktop also works if you already have it, but it needs a paid subscription for companies with more than
250 employees or more than 10 million US dollars of revenue. On Windows without administrator rights, with WSL
disabled by your organisation, or without virtualisation, ask your IT team for one of the two: `kaosctl` cannot work around
that.

## Options

| Option | |
|---|---|
| `[step]` | the step to build (default: every step with a Dockerfile) |
| `--path DIR` | your app folder (default: the current folder) |
| `--arch amd64\|arm64` | the architecture to build for (default `amd64`, or `$KAOS_BUILD_ARCH`) |
| `--engine docker\|podman` | the engine command to use when both are installed |
| `--kaos-lib REQUIREMENT`, `--context FILE` | the kaos-lib the build passes, as in [`kaosctl dev`](dev.md) |
| `--registry-url URL` | the `REGISTRY_URL` build argument |
| `--dry-run` | run the doctor and print the build command; build nothing |
