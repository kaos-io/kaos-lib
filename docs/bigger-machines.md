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

`step("gpu-check", kind="train", reads=["experiment"], gpu=True)` is the whole change. The example step prints the
GPU it got and does a few seconds of work on it. It stops at once, with a message, when torch cannot see a GPU,
because a GPU step that trains on the CPU for hours is the failure to rule out.

[Send it in](first-step.md#send-the-change-in), run the pipeline, and read the log of `gpu-check`:

```text
[gpu-check] GPU visible: NVIDIA L4 (1 device(s))
[gpu-check] ran on NVIDIA L4: 20.3 TFLOPS (fp16 matmul). The GPU works.
```

The name and the number depend on the class you picked.

## When the GPU is not there

On the platform's GPU machines, the platform checks before your code starts that the NVIDIA driver can be used. When it
cannot, the step fails in its first second:

```text
KAOS: this GPU step cannot reach the NVIDIA driver (libcuda.so.1 not found: ...); the image or node is not set up for GPU
```

Pick a class that has a GPU. If you did, tell your platform contact. If a GPU step is given a class without a GPU, it
runs on the CPU and the check is skipped.

Your image decides whether torch uses the GPU:

- Install a CUDA-enabled torch. The default `pip install torch` wheel on Linux is; a CPU-only build never uses the GPU.
- Keep a shell in the image. The platform starts a GPU step through `/bin/sh`.
- `kaosctl lint` warns (`L-D08`) about a GPU step whose Dockerfile starts from a plain base image without the NVIDIA
  driver paths.

## Rules

- A step that sits idle (no GPU use and no new log line for 20 minutes) ends as idle, so the GPU stops costing money.
  `idle_timeout="40m"` on the step changes the time, `idle_timeout=0` turns the rule off.
- Several steps of one project on one HPC class may share a node ([page 9](hpc.md)); compute only on the GPU the
  step is given.

Next: [Long jobs](long-jobs.md).
