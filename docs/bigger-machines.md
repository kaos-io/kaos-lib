# 7. Bigger machines

You have the run form, and on it a field for each step named `<step>-class`. It lists the machines your project can
use. Pick a class for a step when you submit, and the step gets the whole machine of that class.

There is nothing to set for CPU, memory or disk. `pipeline.py` has no keyword for them, and a step that passes
`disk=` fails the render. A step that needs more of anything gets a bigger class.

## A step that needs a GPU

A step declares `gpu=True`, and its class field then starts on a GPU class. The template ships a small GPU step, in
`examples/gpu_check/`, and a commented line in `pipeline.py`. Copy the step's folder and take the comment off the
line:

```bash
cp -r examples/gpu_check steps/gpu_check
```

```python title="pipeline.py" hl_lines="23"
--8<-- "examples/first-pipeline/gpu/pipeline.py"
```

`step("gpu-check", kind="evaluate", reads=["experiment"], gpu=True)` is the whole change. The example step prints the
GPU it got and does a few seconds of work on it. It stops at once, with a message, when torch cannot see a GPU,
because a GPU step that trains on the CPU for hours is the failure to rule out.

[Send it in](first-step.md#send-the-change-in), run the pipeline, and read the log of `gpu-check`:

```text
[gpu-check] GPU visible: NVIDIA L4 (1 device(s))
[gpu-check] ran on NVIDIA L4: 20.3 TFLOPS (fp16 matmul). The GPU works.
```

The name and the number depend on the class you picked.

## When the GPU is not there

On the platform's GPU machines the step fails in its first second, with a message about the NVIDIA driver
([the message](when-something-goes-wrong.md#a-run-fails)), when the GPU cannot be used. Pick a class that has a GPU. If
you did, tell your platform contact. A GPU step that is given a class without a GPU runs on the CPU.

Your image decides whether torch uses the GPU. Install a CUDA-enabled torch: the default `pip install torch` wheel on
Linux is one, and a CPU-only build never uses the GPU. `kaosctl lint` warns (`L-D08`) about a GPU step whose image shows
no CUDA support.

A GPU step that sits idle ends as idle, so the GPU stops costing money ([the limits](contract.md#the-limits)).
Several steps of one project may share a node on HPC ([page 9](hpc.md)); [GPUs on HPC (Slurm)](gpus-on-hpc.md) shows the code that is right with either.

Next: [Long jobs](long-jobs.md).
