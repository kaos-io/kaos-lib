"""prepare-data: the run's dataset, or a reproducible subset of it, as the dataset `prepared`."""
from kaos_lib import step

from app import subset


def main() -> None:
    ctx = step.start()
    data = ctx.params["data"]
    size = int(data["sample_size"]) if str(data.get("sample_size") or "").strip() else None  # empty: every image
    if size is not None and size < 1:
        raise SystemExit(f"data.sample_size must be a positive number or empty, got {size}")
    raw, prepared = step.input("dataset"), step.output("prepared")
    if not (raw / "data.yaml").is_file():
        raise SystemExit("the dataset has no data.yaml at its root: it is not a YOLO dataset (data.yaml, images/, labels/)")
    found = subset.write(raw, prepared, size, int(data["seed"]))
    step.check("prepared", min_files=2)
    print(f"[prepare-data] kept {found}", flush=True)
    step.result(sample_size=size, seed=int(data["seed"]), splits=found)


if __name__ == "__main__":
    main()
