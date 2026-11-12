"""final: works with or without the result and the report of `extra`."""
from kaos_lib import step


def main() -> None:
    step.start()
    extra = step.upstream("extra", optional=True)  # None when `extra` was skipped
    report = step.input("extra-report", optional=True)  # None as well
    if extra is None:
        line = "extra was skipped"
    else:
        line = f"extra ran, score {extra.values['score']}: {(report / 'extra.txt').read_text().strip()}"
    (step.output("final-report") / "final.txt").write_text(line + "\n")
    step.result(extra_ran=extra is not None)


if __name__ == "__main__":
    main()
