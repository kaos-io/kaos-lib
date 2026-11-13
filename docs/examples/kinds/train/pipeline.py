"""train: train a model on a dataset and keep a checkpoint, so that a cut-short run continues."""
from pathlib import Path

from kubecore.authoring import model, pipeline, step  # provided by the platform

with pipeline("ml-pipeline") as p:
    train = step("train", kind="train", reads=["train"], inputs=["dataset"], walltime="6h", resumable=True,
                 produces=[model("model")])

if __name__ == "__main__":
    p.write(Path(__file__).parent / "out" / "raw-workflow-template.yaml")
