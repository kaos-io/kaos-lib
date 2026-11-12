"""work: runs only when check let the run go on."""
from kaos_lib import step


def main() -> None:
    step.start()
    checked = step.upstream("check")
    (step.output("report") / "report.txt").write_text(f"checked for {checked.values['epochs']} epochs\n")
    step.result()


if __name__ == "__main__":
    main()
