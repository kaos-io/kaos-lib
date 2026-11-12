"""filter: copy the files of the input that are big enough into the dataset `filtered`."""
import shutil

from kaos_lib import step


def main() -> None:
    ctx = step.start()
    source = step.input("dataset")
    kept = step.output("filtered")  # an empty folder: what it holds at step.result() becomes the new version
    minimum = ctx.params["filter"]["min_bytes"]
    files = [f for f in source.rglob("*") if f.is_file() and f.stat().st_size >= minimum]
    for f in files:
        target = kept / f.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(f, target)
    print(f"[filter] kept {len(files)} files", flush=True)
    step.result(kept=len(files))


if __name__ == "__main__":
    main()
