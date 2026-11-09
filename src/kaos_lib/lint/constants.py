"""Named values of the pipeline linter: the rule-set version, limits, thresholds and documentation links.

Every number a rule or a limit depends on lives here, so a change to a threshold is one reviewed line and a
rule-set version bump, never a literal buried in a rule.
"""

# The rule-set version: every report carries it, the PR gate and `kaosctl lint` must agree on it. Bump the major
# for a rule removed or a level raised, the minor for a rule added or a message-only change that needs a note,
# the patch for a fix that changes no finding on valid input.
RULESET_VERSION = "1.0.0"

# Where a rule's page lives. The site is a plain public bucket, so every link names its .html file.
DOC_BASE = "https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/lint/"

# Limits that keep a hostile repository from exhausting the linter (it fails with an error finding, never a crash).
MAX_FILE_BYTES = 1024 * 1024          # one file read by the linter
MAX_STEP_FILES = 300                  # Python files read per step folder
MAX_STEP_BYTES = 4 * 1024 * 1024      # all step source read, together

PIPELINE_FILE = "pipeline.py"
CONFIG_DIR = "config"
STEPS_DIR = "steps"

# What the library's step() accepts, in order (positional arguments map onto it).
STEP_PARAMS = ("name", "reads", "gpu", "needs", "outputs", "when", "disk", "hpc_time_limit", "resumable",
               "checkpoint_every", "idle_timeout")

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
