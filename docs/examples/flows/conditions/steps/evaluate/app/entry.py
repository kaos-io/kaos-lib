"""evaluate: scores the model and hands the verdict on as values, so that the next step can use it in `when=`."""
from kaos_lib import step


def main() -> None:
    ctx = step.start()
    epochs = step.upstream("train").values["epochs"]
    score = epochs / 10                                  # a stand-in for a real measurement
    passed = score >= ctx.params["evaluate"]["threshold"]
    (step.output("verdict") / "verdict.txt").write_text(f"score {score}: {'passed' if passed else 'not good enough'}\n")
    step.result(passed=passed, score=score)


if __name__ == "__main__":
    main()
