"""sweep: one step tries several learning rates and keeps the best model."""
from pathlib import Path

from kubecore.authoring import model, pipeline, step  # provided by the platform

with pipeline("ml-pipeline") as p:
    train = step("train", kind="train", reads=["train"], produces=[model("best-model")])

if __name__ == "__main__":
    p.write(Path(__file__).parent / "out" / "raw-workflow-template.yaml")
