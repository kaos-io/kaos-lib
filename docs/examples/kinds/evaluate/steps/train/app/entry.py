"""train: write a model (a stand-in for the real training, which the page Train shows)."""
from kaos_lib import step


def main() -> None:
    step.start()
    (step.output("model") / "weights.txt").write_text("0.8\n")
    step.result()


if __name__ == "__main__":
    main()
