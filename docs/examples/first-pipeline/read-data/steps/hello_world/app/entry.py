"""hello-world: count the files `prepare` wrote in this run and in the reference dataset, and save a small report."""
from kaos_lib import step


def main() -> None:
    ctx = step.start()
    title = ctx.params["hello"]["title"]  # a setting: config/hello.yaml, a field on the run form
    clean = step.input("clean")  # the version of the dataset `clean` that `prepare` wrote in this run
    files = [f for f in clean.rglob("*") if f.is_file()]
    size = sum(f.stat().st_size for f in files)
    reference = sum(1 for f in step.input("reference").rglob("*") if f.is_file())  # the version picked on the form
    dropped = step.upstream("prepare").values["dropped"]  # a value `prepare` handed on
    line = (f"{title} ({ctx.experiment}): {len(files)} files ({size} bytes) in clean, {reference} in the reference, "
            f"{dropped} dropped by prepare")
    (step.output("report") / "hello.txt").write_text(line + "\n")
    print(f"[hello-world] {line}", flush=True)
    step.result(files=len(files), size=size, reference=reference)


if __name__ == "__main__":
    main()
