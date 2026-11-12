"""fetch: copy the files of the source into the dataset `raw`. A real step downloads them instead."""
import shutil
from pathlib import Path

from kaos_lib import step


def main() -> None:
    ctx = step.start()
    source = Path(ctx.params["source"]["folder"])  # stands in for the outside source
    raw = step.output("raw")
    files = sorted(f for f in source.glob("*.csv") if f.is_file())
    for f in files:  # replace this loop with your download, and write what you get into `raw`
        shutil.copy(f, raw / f.name)
    step.check("raw", min_files=1)  # the step fails, and saves nothing, when the source gave no file
    print(f"[fetch] brought in {len(files)} files", flush=True)
    step.result(files=len(files))


if __name__ == "__main__":
    main()
