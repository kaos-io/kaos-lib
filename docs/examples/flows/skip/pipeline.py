"""final: a step after one that may be skipped."""
from pathlib import Path

from kubecore.authoring import artifact, pipeline, step  # provided by the platform

with pipeline("ml-pipeline") as p:
    base = step("base", kind="transform", produces=[artifact("summary")])
    # The condition names a field of the run form: the setting extra.mode is the field extra-mode.
    extra = step("extra", kind="evaluate", needs=[base], when="{{workflow.parameters.extra-mode}} != off",
                 produces=[artifact("extra-report")])
    final = step("final", kind="publish", needs=[base, extra], produces=[artifact("final-report")])

if __name__ == "__main__":
    p.write(Path(__file__).parent / "out" / "raw-workflow-template.yaml")
