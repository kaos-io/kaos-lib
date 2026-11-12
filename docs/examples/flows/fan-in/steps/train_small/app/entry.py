"""train-small: a stand-in for a training: the score is the number of epochs."""
from kaos_lib import step


def main() -> None:
    ctx = step.start()
    epochs = ctx.params["train"]["small_epochs"]
    (step.output("small") / "weights.txt").write_text(f"small model, {epochs} epochs\n")
    step.result(score=epochs)


if __name__ == "__main__":
    main()
