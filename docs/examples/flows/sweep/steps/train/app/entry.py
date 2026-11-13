"""train: runs once for each combination of matrix=. The values of its combination are settings like any other."""
from kaos_lib import step


def train_once(learning_rate: float, batch: int, epochs: int) -> float:
    """A stand-in for a real training run: returns the final loss."""
    return abs(learning_rate - 0.01) + 1 / batch + 1 / (epochs * 100)


def main() -> None:
    ctx = step.start()
    lr, batch = ctx.params["lr"], ctx.params["batch"]         # this combination's values, beside ctx.params["train"]
    loss = train_once(lr, batch, ctx.params["train"]["epochs"])
    (step.output("model") / "weights.txt").write_text(f"learning rate {lr}, batch {batch}\n")
    step.result(loss=loss)


if __name__ == "__main__":
    main()
