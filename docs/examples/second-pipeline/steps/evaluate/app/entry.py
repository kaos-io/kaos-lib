"""evaluate: count the files of the dataset `clean` that another pipeline produced."""
from kaos_lib import step


def main() -> None:
    step.start()
    clean = step.input("clean")  # the same call as for a dataset made by hand
    files = sum(1 for f in clean.rglob("*") if f.is_file())
    (step.output("report") / "evaluate.txt").write_text(f"{files} files in clean\n")
    step.result(files=files)


if __name__ == "__main__":
    main()
