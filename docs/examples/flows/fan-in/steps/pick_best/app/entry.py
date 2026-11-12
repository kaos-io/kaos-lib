"""pick-best: keep the model of the step with the higher score."""
import shutil

from kaos_lib import step


def main() -> None:
    step.start()
    scores = {name: step.upstream(f"train-{name}").values["score"] for name in ("small", "large")}  # two results
    winner = max(scores, key=scores.get)
    shutil.copytree(step.input(winner), step.output("winner"), dirs_exist_ok=True)  # the folder of that model
    step.result(winner=winner, **{f"score_{name}": score for name, score in scores.items()})


if __name__ == "__main__":
    main()
