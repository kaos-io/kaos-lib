"""train: one training step that is right on one GPU and on four."""
from pathlib import Path

from kubecore.authoring import model, pipeline, step  # provided by the platform

with pipeline("ml-pipeline") as p:
    train = step("train", kind="train", reads=["train"], inputs=["dataset"], gpu=True, walltime="6h", resumable=True,
                 produces=[model("model")])

if __name__ == "__main__":
    p.write(Path(__file__).parent / "out" / "raw-workflow-template.yaml")
