"""train: the same code on one GPU or four. It asks how many GPUs it has, and sizes the work from the answer."""
from kaos_lib import checkpoint, runtime, step


def plan(gpus: int, cpus: int, batch_per_gpu: int) -> dict:
    """What to run with `gpus` GPUs and `cpus` cores: the batch grows with the GPUs, the loader workers are the cores."""
    gpus = max(1, gpus)
    return {"gpus": gpus, "batch": batch_per_gpu * gpus, "workers": max(1, cpus), "parallel": gpus > 1}


def main() -> None:
    import torch  # the step's image installs it ([Add packages](add-packages.md))

    ctx = step.start()
    slot = runtime.context().slot  # None on the platform's own machines; on HPC (Slurm), this step's share of the node
    gpus = slot.gpus if slot and slot.gpus else torch.cuda.device_count()  # never a number written in the code
    p = plan(gpus, runtime.usable_cpus(), ctx.params["train"]["batch_per_gpu"])
    print(f"[train] {p['gpus']} GPU(s), batch {p['batch']}, {p['workers']} loader workers", flush=True)

    device = "cuda" if p["gpus"] and torch.cuda.is_available() else "cpu"
    model = torch.nn.Linear(8, 1).to(device)
    if p["parallel"]:
        model = torch.nn.DataParallel(model)  # one process that splits each batch over the GPUs it sees
    state = checkpoint.load("state", default={"epoch": 0})  # the same checkpoint code on one GPU or four
    for epoch in range(state["epoch"], ctx.params["train"]["epochs"]):
        batch = torch.randn(p["batch"], 8, device=device)  # your data loader goes here: num_workers=p["workers"]
        model(batch).sum().backward()
        state["epoch"] = epoch + 1
        checkpoint.save(state)
    weights = model.module if p["parallel"] else model
    torch.save(weights.state_dict(), step.output("model") / "weights.pt")
    step.result(gpus=p["gpus"], epochs=state["epoch"])


if __name__ == "__main__":
    main()
