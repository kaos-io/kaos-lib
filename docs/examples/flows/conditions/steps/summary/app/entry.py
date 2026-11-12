"""summary: says what happened, whether publish ran, skipped itself or was not asked to run."""
from kaos_lib import step


def main() -> None:
    step.start()
    verdict = step.upstream("evaluate").values
    published = step.upstream("publish", optional=True)           # None when publish did not run or skipped itself
    if published is not None:
        line = f"score {verdict['score']}: published as {published.values['delivered']}"
    elif step.skipped("publish"):                                  # the reason publish gave to step.skip()
        line = f"score {verdict['score']}: not published, {step.skipped('publish')}"
    else:                                                          # "": publish did not run, its `when=` was false
        line = f"score {verdict['score']}: not published, the model did not pass"
    (step.output("summary-report") / "summary.txt").write_text(line + "\n")
    step.result(published=published is not None)


if __name__ == "__main__":
    main()
