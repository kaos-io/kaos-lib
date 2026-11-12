"""register: deliver the model the step before it made. A publish step produces nothing here."""
from pathlib import Path

from kubecore.authoring import model, pipeline, step  # provided by the platform

with pipeline("ml-pipeline") as p:
    train = step("train", kind="train", produces=[model("model")])
    register = step("register", kind="publish", needs=[train], reads=["registry"])

if __name__ == "__main__":
    p.write(Path(__file__).parent / "out" / "raw-workflow-template.yaml")
