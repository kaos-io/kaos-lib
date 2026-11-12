"""train: write the model (a real step trains one)."""
from kaos_lib import step


def main() -> None:
    step.start()
    (step.output("model") / "weights.txt").write_text("weights\n")
    step.result()


if __name__ == "__main__":
    main()
