"""train: log what a run produced to the project's MLflow, and save the model."""
import mlflow
from kaos_lib import mlflow as tracking
from kaos_lib import step


def main() -> None:
    ctx = step.start()
    epochs = ctx.params["train"]["epochs"]
    tracking.mlflow()  # signs the step in and points `mlflow` at the project's server; fails here without a credential
    # The project's MLflow takes only the names `<app>` or `<app>.<something>`: the app's name goes first.
    mlflow.set_experiment(ctx.app if ctx.experiment == ctx.app else f"{ctx.app}.{ctx.experiment}")
    with mlflow.start_run(run_name=ctx.run):
        mlflow.log_param("epochs", epochs)
        for epoch in range(1, epochs + 1):
            mlflow.log_metric("loss", 1 / epoch, step=epoch)  # a curve: one point for each epoch
    (step.output("model") / "weights.txt").write_text(f"trained for {epochs} epochs\n")
    step.result(final_loss=1 / epochs)


if __name__ == "__main__":
    main()
