"""sweep: one step runs once for each combination of values, and the step after it picks the best."""
from pathlib import Path

from kubecore.authoring import artifact, model, pipeline, step  # provided by the platform

with pipeline("ml-pipeline") as p:
    train = step("train", kind="train", reads=["train"], produces=[model("model")],
                 matrix={"lr": [0.1, 0.01, 0.001], "batch": [16, 32]}, matrix_allow_failed=True)
    pick = step("pick-best", kind="evaluate", needs=[train], produces=[artifact("winner")])

if __name__ == "__main__":
    p.write(Path(__file__).parent / "out" / "raw-workflow-template.yaml")
