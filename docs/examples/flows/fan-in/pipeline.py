"""pick-best: one step that needs two others."""
from pathlib import Path

from kubecore.authoring import artifact, model, pipeline, step  # provided by the platform

with pipeline("ml-pipeline") as p:
    small = step("train-small", kind="train", reads=["train"], produces=[model("small")])
    large = step("train-large", kind="train", reads=["train"], produces=[model("large")])
    pick = step("pick-best", kind="evaluate", needs=[small, large], produces=[artifact("winner")])

if __name__ == "__main__":
    p.write(Path(__file__).parent / "out" / "raw-workflow-template.yaml")
