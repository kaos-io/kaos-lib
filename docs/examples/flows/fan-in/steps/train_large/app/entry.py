"""train-large: a stand-in for a training: the score is the number of epochs."""
from kaos_lib import step


def main() -> None:
    ctx = step.start()
    epochs = ctx.params["train"]["large_epochs"]
    (step.output("large") / "weights.txt").write_text(f"large model, {epochs} epochs\n")
    step.result(score=epochs)


if __name__ == "__main__":
    main()
