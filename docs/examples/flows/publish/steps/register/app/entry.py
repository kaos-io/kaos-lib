"""register: deliver the model that the step before it made. A real step calls your registry or your service."""
from kaos_lib import step


def main() -> None:
    ctx = step.start()
    weights = step.input("model")  # the model `train` wrote, by its name in produces=
    name = ctx.params["registry"]["name"]
    files = sorted(f.name for f in weights.iterdir())  # replace this with the delivery of the files
    print(f"[register] delivered {name}: {', '.join(files)}", flush=True)
    step.result(delivered=name)  # the next step, and the run, can see what was delivered


if __name__ == "__main__":
    main()
