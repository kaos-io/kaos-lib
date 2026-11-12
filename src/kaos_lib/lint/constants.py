"""Named values of the pipeline linter: the rule-set version, limits, thresholds and documentation links.

Every number a rule or a limit depends on lives here, so a change to a threshold is one reviewed line and a
rule-set version bump, never a literal buried in a rule.
"""

# The rule-set version: every report carries it, the PR gate and `kaosctl lint` must agree on it. Bump the major
# for a rule removed or a level raised, the minor for a rule added or a message-only change that needs a note,
# the patch for a fix that changes no finding on valid input.
RULESET_VERSION = "2.0.0"

# Where a rule's page lives. The site is a plain public bucket, so every link names its .html file.
DOC_BASE = "https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/lint/"

# Limits that keep a hostile repository from exhausting the linter (it fails with an error finding, never a crash).
MAX_FILE_BYTES = 1024 * 1024          # one file read by the linter
MAX_STEP_FILES = 300                  # Python files read per step folder
MAX_STEP_BYTES = 4 * 1024 * 1024      # all step source read, together
MAX_REASON_CHARS = 300                # the platform's reason for a step's evidence, as the platform bounds it

PIPELINE_FILE = "pipeline.py"
CONFIG_DIR = "config"
STEPS_DIR = "steps"

# What the library's step() accepts, in order (positional arguments map onto it).
STEP_PARAMS = ("name", "kind", "reads", "inputs", "needs", "produces", "gpu", "disk", "when", "walltime",
               "resumable", "checkpoint_every", "idle_timeout")
# Arguments step() took before the step contract of kaos-lib 0.5, and what to do about each.
REMOVED_STEP_PARAMS = {
    "hpc_time_limit": "Rename it to walltime.",
    "outputs": "Remove it: a step hands values on with step.result(...), and a step that needs them reads "
               "step.upstream(...).values.",
}
# What a step is (kind=), and what it may declare in produces=[...].
STEP_KINDS = ("ingest", "transform", "train", "evaluate", "publish", "control")
PRODUCE_TYPES = ("model", "artifact", "dataset")
RESERVED_NAME_PREFIX = "kaos-"
NAME_MAX = 40                        # characters of a step name, an input name and a produces name
MAX_NEEDS = 10                       # steps in one step's needs=: each may hand on a result of up to 8 KiB
# What `kaosctl lint --fix` writes for a missing kind: it is not a kind, so the check keeps failing until one is chosen.
KIND_PLACEHOLDER = "choose one: " + " | ".join(STEP_KINDS)
# What step code used before the step contract: finding one means the step was not moved to kaos_lib.step.
OLD_ENTRY_ARGUMENT = "--params"
OLD_ENTRY_VARIABLES = ("KUBECORE_RUN_ID", "KUBECORE_WORKFLOW_NAME", "CHECKPOINT_BUCKET", "CHECKPOINT_PREFIX",
                       "OUTPUTS_REPO",
                       "KUBECORE_DATASET_REF", "KUBECORE_DATASET_COMMIT", "DATASET_REPO", "DATASET_REF",
                       "DATASET_COMMIT", "KUBECORE_STAGED_DIR", "KAOS_LIB_LOCK")
MIGRATION_URL = DOC_BASE[: -len("lint/")] + "migrate-to-0.5.html"

# A DNS-label step name, as the library requires.
STEP_NAME_PATTERN = r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$"
# A Kubernetes quantity such as 20Gi; a time such as 90m, 12h or 720 (minutes).
DISK_PATTERN = r"^[0-9]+(Ki|Mi|Gi|Ti|K|M|G|T)?$"
TIME_PATTERN = r"^[0-9]+[mh]?$"

# Template names only the platform may produce (the HPC (Slurm) follower and its earlier name).
RESERVED_TEMPLATE_NAMES = ("hpc-follower", "meluxina-run")
# Keyword and dictionary names that give a pipeline its own identity or patch its pod.
IDENTITY_NAMES = ("service_account_name", "serviceAccountName")
POD_PATCH_NAMES = ("pod_spec_patch", "podSpecPatch")
COMPUTE_CLASS_KEYS = ("platform.kubecore.io/compute-class",)

# Thresholds (owner review, OQ-13).
LONG_GPU_STEP_MINUTES = 4 * 60        # L-W01: the HPC (Slurm) default limit
SHORT_LIMIT_MINUTES = 2 * 60          # L-I02: a limit under this may be shortened by the platform

# The built-in default catalogue: only facts that hold for every project.
DEFAULT_LANE_MAX_MINUTES = 2 * 24 * 60   # the longest run of the default HPC (Slurm) lane: 2 days
DEFAULT_MAX_CONTINUATIONS = 5            # a resumable step continues at most this many times
DEFAULT_LIMIT_MINUTES = 4 * 60           # the limit of a GPU step that sets none

# Frameworks the library hooks for checkpoints when the step imports them.
CHECKPOINT_FRAMEWORKS = ("ultralytics", "pytorch_lightning", "lightning", "transformers")
# Static evidence that a step's code keeps checkpoints: the folder the platform restores, or the state functions.
CHECKPOINT_DIR_ENV = "KAOS_CHECKPOINT_DIR"
CHECKPOINT_STATE_NAMES = ("save_state", "load_state")

# The Dockerfile doctor (rules L-D01 .. L-D08, PRD-CONSOLE-1682 D-19).
BUILD_ARCH_DEFAULT = "amd64"           # the platform's step images are built for this unless the project says otherwise
COMPOSE_STEP = "compose-and-validate"  # built with the repository root as context, not its own folder
LARGE_COPY_BYTES = 50 * 1024 * 1024    # L-D06: a COPY source folder above this is a layer you probably did not mean
DATA_FOLDER_NAMES = ("data", "dataset", "datasets", "weights", "runs", "out", "outputs", "checkpoints", ".git")
DRIVER_PATH = "/usr/local/nvidia"       # L-D08: where GKE and EKS GPU nodes mount the NVIDIA driver
CUDA_IMAGE_WORDS = ("cuda", "nvidia", "pytorch", "tensorflow", "rocm")
CUDA_PACKAGE_PATTERN = (r"(?<![a-z0-9_-])(torch|torchvision|tensorflow|jax|jaxlib|cupy|onnxruntime-gpu|ultralytics|"
                        r"cudf|nvidia-[a-z0-9-]+)(?![a-z0-9_])")
KAOS_LIB_ARG = "KAOS_LIB_PACKAGE"
ENTRY_MODULE = "app.entry"
