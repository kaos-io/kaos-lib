"""A second pipeline: it evaluates the dataset `clean` that the first pipeline (the app `myapp`) produces."""
from pathlib import Path

from kubecore.authoring import artifact, pipeline, step  # provided by the platform

with pipeline("ml-pipeline") as p:
    evaluate = step("evaluate", kind="evaluate", inputs=["clean"], produces=[artifact("report")])

if __name__ == "__main__":
    p.write(Path(__file__).parent / "out" / "raw-workflow-template.yaml")
