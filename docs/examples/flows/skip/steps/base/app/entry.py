"""base: always runs."""
from kaos_lib import step


def main() -> None:
    step.start()
    (step.output("summary") / "summary.txt").write_text("base ran\n")
    step.result(base=True)


if __name__ == "__main__":
    main()
