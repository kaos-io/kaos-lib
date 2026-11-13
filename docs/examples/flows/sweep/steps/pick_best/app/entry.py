"""pick-best: reads the list of what every combination of `train` handed on, and keeps the model of the best one."""
import shutil

from kaos_lib import step


def main() -> None:
    step.start()
    items = step.upstream("train")                            # one entry for each combination, in order
    done = [item for item in items if item.status == "ok"]    # a failed or skipped combination has no values
    best = min(done, key=lambda item: item.values["loss"])
    shutil.copytree(step.input("model", item=best.index), step.output("winner"), dirs_exist_ok=True)
    step.result(best_index=best.index, best_lr=best.matrix["lr"], best_batch=best.matrix["batch"],
                best_loss=best.values["loss"], tried=len(items), finished=len(done))


if __name__ == "__main__":
    main()
