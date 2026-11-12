"""fetch: bring data in from outside as the dataset `raw`."""
from pathlib import Path

from kubecore.authoring import dataset, pipeline, step  # provided by the platform

with pipeline("ml-pipeline") as p:
    fetch = step("fetch", kind="ingest", reads=["source"], produces=[dataset("raw")])

if __name__ == "__main__":
    p.write(Path(__file__).parent / "out" / "raw-workflow-template.yaml")
