"""train: tries every learning rate of the setting, in a loop, and keeps the best model."""
from kaos_lib import step


def train_once(learning_rate: float, epochs: int) -> float:
    """A stand-in for a real training run: returns the final loss."""
    return abs(learning_rate - 0.01) + 1 / epochs


def main() -> None:
    ctx = step.start()
    rates = [float(r) for r in ctx.params["train"]["learning_rates"].split(",")]
    losses = {rate: train_once(rate, ctx.params["train"]["epochs"]) for rate in rates}
    best = min(losses, key=losses.get)
    (step.output("best-model") / "weights.txt").write_text(f"learning rate {best}\n")
    step.result(best_learning_rate=best, best_loss=losses[best], tried=len(rates))


if __name__ == "__main__":
    main()
