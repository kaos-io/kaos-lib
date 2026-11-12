"""train: make several passes over `clean`, and after an interruption continue from the last finished one."""
from kaos_lib import checkpoint, step


def main() -> None:
    ctx = step.start()
    clean = step.input("clean")
    epochs = ctx.params["train"]["epochs"]
    state = checkpoint.load("state", default={"epoch": 0, "seen": 0})  # a first run: the default
    for epoch in range(state["epoch"], epochs):
        size = sum(f.stat().st_size for f in clean.rglob("*") if f.is_file())
        state["seen"] += size  # one pass over the data: your training goes here
        state["epoch"] = epoch + 1
        checkpoint.save(state)
        print(f"[train] epoch {state['epoch']} of {epochs} done", flush=True)
        if checkpoint.stop_requested():  # the platform needs the machine back
            checkpoint.exit_for_restart()  # exit code 85: "saved, run me again"
    (step.output("model") / "weights.txt").write_text(f"{state['seen']}\n")
    step.result(epochs=epochs)


if __name__ == "__main__":
    main()
