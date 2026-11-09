"""Named values of the local studio: folders, thresholds and lists. A change to one is one reviewed line."""

LOCAL_DIR = ".kaos/local"          # everything kaosctl writes for a local run, in the repository, git-ignored by itself
VENV_DIR = ".venv"                 # a step's virtual environment, inside its folder
SETTINGS_DIR = ".vscode"
SETTINGS_FILE = "settings.json"
STEPS_DIR = "steps"
COMPOSE_STEP = "compose-and-validate"

DEFAULT_SAMPLE_MB = 50             # `kaosctl step run --dataset`: the most a local sample downloads
OUTPUT_PRINT_CHARS = 2000          # one output is printed up to this many characters
LOCAL_RUN_ID = "local"

# Dependencies that make a step's environment several GB; `kaosctl dev` skips such steps unless asked (OQ-19).
HEAVY_PACKAGES = ("torch", "torchvision", "torchaudio", "tensorflow", "jax", "jaxlib", "ultralytics", "cupy",
                  "onnxruntime-gpu", "pytorch-lightning", "lightning", "litert-torch", "torchao")

# Build (D-17, F-32).
MIN_FREE_GB = 5                    # the build refuses below this much free space for the engine's images
ENGINE_TIMEOUT_SECONDS = 60        # one probe command of the engine (info, version, a test build)
TEST_BUILD_TIMEOUT_SECONDS = 180
BUILD_ARCH_ENV = "KAOS_BUILD_ARCH"
LOCAL_REGISTRY = "local"           # REGISTRY_URL build argument of a local build (CI passes the platform's registry)
LOCAL_IMAGE_PREFIX = "kaos-local"  # local images are tagged kaos-local/<app>:<step>-local-<sha>: never a registry name
TEST_IMAGE_TAG = "kaos-build-check:test"
OUTPUT_TAIL_LINES = 40             # how much of an engine's output is kept to explain a failure

# What a local run is allowed to inherit from the user's environment (CON-16): an allowlist, never a denylist.
ENV_ALLOW = ("PATH", "HOME", "USERPROFILE", "LANG", "LANGUAGE", "TERM", "TMPDIR", "TEMP", "TMP", "SYSTEMROOT",
             "USER", "LOGNAME", "SHELL", "TZ", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy",
             "no_proxy", "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE")
ENV_ALLOW_PREFIXES = ("LC_",)

# Environment variables only the platform sets for a running step. A step that reads one cannot work on a laptop.
PLATFORM_ENV = ("MLFLOW_TRACKING_URI", "MLFLOW_TRACKING_TOKEN", "LAKEFS_ENDPOINT", "LAKEFS_ACCESS_KEY",
                "LAKEFS_SECRET_KEY", "LAKEFS_BEARER_TOKEN", "CHECKPOINT_BUCKET", "OUTPUTS_REPO",
                "KUBECORE_WORKFLOW_NAME", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "ZITADEL_MACHINE_KEY_FILE",
                "KAOS_CHECKPOINT_DIR")

WORK_PREFIX = "/work"              # the platform's per-step folder; a local run maps it into LOCAL_DIR
