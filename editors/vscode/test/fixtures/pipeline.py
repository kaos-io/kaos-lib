from kubecore.authoring import pipeline, step

with pipeline("demo") as p:
    prepare = step("prepare", disk="20Gi")
    train = step("train", needs=[prepare], gpu=True, walltime="12h", idle_timeout=0)
    step("evaluate", needs=[prepare, train])
