"""conditions: publish only when the model passed, and a summary that works either way."""
from pathlib import Path

from kubecore.authoring import artifact, model, pipeline, step  # provided by the platform

with pipeline("ml-pipeline") as p:
    train = step("train", kind="train", reads=["train"], produces=[model("model")])
    evaluate = step("evaluate", kind="evaluate", reads=["evaluate"], needs=[train], produces=[artifact("verdict")])
    # `evaluate.passed` is the value `passed` that the step evaluate hands on with step.result(passed=...).
    publish = step("publish", kind="publish", reads=["registry"], needs=[evaluate], when="evaluate.passed == true")
    summary = step("summary", kind="evaluate", needs=[evaluate, publish], produces=[artifact("summary-report")])

if __name__ == "__main__":
    p.write(Path(__file__).parent / "out" / "raw-workflow-template.yaml")
