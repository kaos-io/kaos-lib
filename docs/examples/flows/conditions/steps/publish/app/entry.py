"""publish: runs only when the model passed (`when=` in pipeline.py), and skips itself when there is nowhere to deliver."""
from kaos_lib import step


def main() -> None:
    ctx = step.start()
    name = ctx.params["registry"]["name"]
    if not name:
        step.skip("no registry name is set in config/registry.yaml")   # ends the step cleanly: it is not a failure
    step.result(delivered=name)


if __name__ == "__main__":
    main()
