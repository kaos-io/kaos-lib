"""evaluate: measure the model the step before it made, and write a report. It makes no dataset and no model."""
from pathlib import Path

from kubecore.authoring import artifact, model, pipeline, step  # provided by the platform

with pipeline("ml-pipeline") as p:
    train = step("train", kind="train", produces=[model("model")])
    evaluate = step("evaluate", kind="evaluate", reads=["evaluate"], needs=[train], produces=[artifact("report")])

if __name__ == "__main__":
    p.write(Path(__file__).parent / "out" / "raw-workflow-template.yaml")
