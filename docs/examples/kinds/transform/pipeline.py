"""filter: keep the files that are not empty, as the dataset `filtered`."""
from pathlib import Path

from kubecore.authoring import dataset, pipeline, step  # provided by the platform

with pipeline("ml-pipeline") as p:
    filter_files = step("filter", kind="transform", reads=["filter"], inputs=["dataset"],
                        produces=[dataset("filtered")])

if __name__ == "__main__":
    p.write(Path(__file__).parent / "out" / "raw-workflow-template.yaml")
