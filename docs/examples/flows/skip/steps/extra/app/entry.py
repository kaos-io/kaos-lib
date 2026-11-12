"""extra: runs only when the run form asks for it."""
from kaos_lib import step


def main() -> None:
    step.start()
    (step.output("extra-report") / "extra.txt").write_text("extra ran\n")
    step.result(score=7)


if __name__ == "__main__":
    main()
