"""evaluate: score the model of the step before it, write the score as a report and hand the verdict on."""
from kaos_lib import step


def main() -> None:
    ctx = step.start()
    weights = step.input("model")  # the model `train` wrote, by its name in produces=
    score = float((weights / "weights.txt").read_text())  # your measuring goes here
    passed = score >= ctx.params["evaluate"]["threshold"]
    (step.output("report") / "score.txt").write_text(f"score {score}: {'passed' if passed else 'did not pass'}\n")
    step.result(score=score, passed=passed)  # a later step can run only when `evaluate.passed == true`


if __name__ == "__main__":
    main()
