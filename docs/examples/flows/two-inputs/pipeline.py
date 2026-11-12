"""compare: read two versions of a dataset, side by side, and report what changed."""
from pathlib import Path

from kubecore.authoring import artifact, pipeline, step  # provided by the platform

with pipeline("ml-pipeline") as p:
    compare = step("compare", kind="evaluate", inputs=["before", "after"], produces=[artifact("changes")])

if __name__ == "__main__":
    p.write(Path(__file__).parent / "out" / "raw-workflow-template.yaml")
