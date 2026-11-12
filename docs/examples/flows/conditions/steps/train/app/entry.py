"""train: writes a model."""
from kaos_lib import step


def main() -> None:
    ctx = step.start()
    epochs = ctx.params["train"]["epochs"]
    (step.output("model") / "weights.txt").write_text(f"trained for {epochs} epochs\n")
    step.result(epochs=epochs)


if __name__ == "__main__":
    main()
