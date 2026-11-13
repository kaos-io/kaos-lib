"""The command-line arguments of `kaosctl dev`, `kaosctl step run`, `kaosctl render` and `kaosctl build`.

Why: kept apart from `kaos_lib.cli` so the studio is one module that the dispatcher only has to register.
"""
from __future__ import annotations

import argparse

from . import build, dev, pipeline_engine, run
from .constants import DEFAULT_SAMPLE_MB

KAOS_LIB_HELP = ("the kaos-lib to install, as a pip requirement or the path of a checkout, a wheel or an archive on "
                 "this machine (default: the Dockerfile's own default, else this kaosctl's version)")
CONTEXT_HELP = ("the platform's pipeline-context file: its kaosLib.spec is the kaos-lib the platform's build passes, "
                "its engine block the pipeline engine the platform renders with")
ENGINE_WHEEL_HELP = ("the pipeline engine release to use, as its wheel URL with the checksum (default: "
                     "$KAOS_ENGINE_WHEEL, else the engine block of --context)")
PROFILE_HELP = "the engine's config-schema profile (default: yolo for an app with a quantization config, else hera)"


def add_commands(sub: argparse._SubParsersAction) -> None:
    """Register `dev`, `step` and `build` on kaosctl's sub-command parser."""
    sp = sub.add_parser("dev", help="set up a Python environment for each step (no Docker, no cluster)",
                        description="Create one virtual environment per step, inside the step's folder, from what the "
                                    "step's Dockerfile installs (read, never run), with the Python of its base image when "
                                    "this machine has it and kaos-lib added. Uses uv when it is installed, else pip. "
                                    "Safe to run again. Installs nothing outside the repository.")
    sp.add_argument("path", nargs="?", default=".", help="your app folder (default: the current folder)")
    sp.add_argument("--step", action="append", default=[], metavar="NAME", help="set up only this step (repeat for more)")
    sp.add_argument("--all", action="store_true", help="also set up steps whose dependencies are several GB (torch, CUDA)")
    sp.add_argument("--kaos-lib", metavar="REQUIREMENT|PATH", help=KAOS_LIB_HELP)
    sp.add_argument("--context", metavar="FILE", help=CONTEXT_HELP)
    sp.add_argument("--vscode", action="store_true", help="also write .vscode/settings.json in each step folder, "
                    "pointing VS Code at the step's Python (not written otherwise)")
    sp.set_defaults(func=dev.run_dev)

    st = sub.add_parser("step", help="work with one step of your pipeline on this machine")
    ssub = st.add_subparsers(dest="step_command", required=True)
    sp = ssub.add_parser("run", help="run one step locally, as the platform runs it",
                         description="Run one step in its own environment the way the platform starts it: python -m "
                                     "app.entry with no arguments and the step context, which kaos_lib.step reads. "
                                     "Inputs are folders on this machine, outputs stay in .kaos/local, and the "
                                     "step's result is kept for the next step. No cluster, no platform secret.")
    sp.add_argument("step", help="the step's name, as in pipeline.py")
    sp.add_argument("path", nargs="?", default=".", help="your app folder (default: the current folder)")
    sp.add_argument("--params-file", metavar="FILE", help="use this params.yaml instead of composing one from config/")
    sp.add_argument("--set", dest="override", action="append", default=[], metavar="KEY=VALUE",
                    help="a config override for the composition (Hydra syntax, repeat for more)")
    sp.add_argument("--input", action="append", default=[], metavar="NAME=FOLDER|REPO@REF",
                    help="what the step gets for the input NAME (a name in its inputs=): a folder on this machine, "
                         "or a small sample of a dataset version (needs `kaosctl login`). Repeat for more")
    sp.add_argument("--matrix-index", type=int, metavar="N",
                    help="for a step with matrix= in pipeline.py: run item N, the Nth combination of its values (the "
                         "first name changing slowest, counting from 0). A step with matrix= needs it")
    sp.add_argument("--upstream", action="append", default=[], metavar="STEP=JSON|@FILE",
                    help="the result of a step this one needs (default: that step's last local run; without one "
                         "the step is treated as not run)")
    sp.add_argument("--sample-mb", type=int, default=DEFAULT_SAMPLE_MB, metavar="MB",
                    help=f"the most the sample downloads (default {DEFAULT_SAMPLE_MB})")
    sp.add_argument("--python", metavar="INTERPRETER",
                    help="run the step with this existing Python (it must have kaos-lib) instead of building an "
                         "environment: for steps with heavy dependencies")
    sp.add_argument("--kaos-lib", metavar="REQUIREMENT|PATH", help=KAOS_LIB_HELP)
    sp.add_argument("--context", metavar="FILE", help=CONTEXT_HELP)
    sp.add_argument("--engine-wheel", metavar="URL#sha256=HEX", help=ENGINE_WHEEL_HELP)
    sp.add_argument("--profile", choices=pipeline_engine.PROFILES, help=PROFILE_HELP)
    sp.set_defaults(func=run.run_step)

    sp = sub.add_parser("render", help="render pipeline.py with the platform's pipeline engine, as its CI does",
                        description="Fetch the pipeline engine release the platform pinned for your app (checked by "
                                    "its SHA-256), install it into .kaos/engine inside the repository, and render "
                                    "pipeline.py with it. The result is out/raw-workflow-template.yaml. A render "
                                    "that passes here passes in CI.")
    sp.add_argument("path", nargs="?", default=".", help="your app folder (default: the current folder)")
    sp.add_argument("--context", metavar="FILE", help=CONTEXT_HELP)
    sp.add_argument("--engine-wheel", metavar="URL#sha256=HEX", help=ENGINE_WHEEL_HELP)
    sp.add_argument("--profile", choices=pipeline_engine.PROFILES, help=PROFILE_HELP)
    sp.set_defaults(func=pipeline_engine.run_render)

    sp = sub.add_parser("build", help="build a step's image on this machine with the container engine you already have",
                        description="Check the Dockerfile (the Dockerfile doctor), find and verify a container engine "
                                    "(Docker, Podman, Colima, Rancher Desktop), and build the step image with the same "
                                    "inputs as the platform's CI. With no usable engine it prints what to install for "
                                    "your OS and stops: kaosctl never installs anything. The image stays on this "
                                    "machine; nothing is pushed.")
    sp.add_argument("step", nargs="?", help="the step to build (default: every step with a Dockerfile)")
    sp.add_argument("--path", default=".", help="your app folder (default: the current folder)")
    sp.add_argument("--arch", choices=build.ARCHES, help="the CPU architecture to build for (default: amd64, or $KAOS_BUILD_ARCH)")
    sp.add_argument("--engine", choices=("docker", "podman"), help="use this engine command when both are installed")
    sp.add_argument("--kaos-lib", metavar="REQUIREMENT", help=KAOS_LIB_HELP)
    sp.add_argument("--context", metavar="FILE", help=CONTEXT_HELP)
    sp.add_argument("--registry-url", metavar="URL", help="the REGISTRY_URL build argument (default: local)")
    sp.add_argument("--dry-run", action="store_true", help="run the doctor and print the build command; build nothing")
    sp.set_defaults(func=build.run_build)
