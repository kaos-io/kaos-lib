"""train: pass over the data in epochs, save the state after each, and write the model."""
from kaos_lib import checkpoint, step


def main() -> None:
    ctx = step.start()
    data = step.input("dataset")
    epochs = ctx.params["train"]["epochs"]
    state = checkpoint.load("state", default={"epoch": 0})  # a first run starts at the default
    for epoch in range(state["epoch"], epochs):
        files = sum(1 for f in data.rglob("*") if f.is_file())  # your training goes here
        state["epoch"] = epoch + 1
        checkpoint.save(state)
        print(f"[train] epoch {state['epoch']} of {epochs}: {files} files", flush=True)
    (step.output("model") / "weights.txt").write_text(f"trained for {epochs} epochs\n")  # a model must be written
    step.result(epochs=epochs)


if __name__ == "__main__":
    main()
