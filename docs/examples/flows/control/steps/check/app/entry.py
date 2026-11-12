"""check: end the run before any machine is spent when its settings cannot work."""
from kaos_lib import step


def main() -> None:
    ctx = step.start()
    epochs = ctx.params["check"]["epochs"]
    if epochs < 1:
        raise SystemExit(f"check.epochs is {epochs}: it must be at least 1.")  # the run stops here
    print(f"[check] {epochs} epochs: fine", flush=True)
    step.result(ok=True, epochs=epochs)  # later steps can read these values


if __name__ == "__main__":
    main()
