"""check: stop the run early when its settings are wrong. A control step handles no data."""
from pathlib import Path

from kubecore.authoring import artifact, pipeline, step  # provided by the platform

with pipeline("ml-pipeline") as p:
    check = step("check", kind="control", reads=["check"])
    work = step("work", kind="evaluate", needs=[check], produces=[artifact("report")])

if __name__ == "__main__":
    p.write(Path(__file__).parent / "out" / "raw-workflow-template.yaml")
