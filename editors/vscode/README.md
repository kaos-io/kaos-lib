# KAOS Pipelines for VS Code

Helps you write and check the `pipeline.py` of a KAOS ML pipeline:

- **Suggestions and docs** while you type a `step(...)` call: argument names, allowed values and a short explanation
  of each. Hover an argument to read about it.
- **Checks as you save.** The same check the pull request runs (`kaosctl lint`) shows its findings as squiggles in
  the file, each with a fix hint and a link to its page. One-click fixes for the simple ones, for example
  `walltime=` becomes `hpc_time_limit=`.
- **A step graph.** A read-only picture of your steps and what each one needs. Click a step to jump to its line.
- **Sign-in** with the same browser sign-in as `kaosctl login`.

The extension reads your files; it never runs your pipeline or your step code.

## Install (from a file)

1. Install `kaosctl` (it comes with the `kaos-lib` package). See the kaos-lib installation page for the index and the
   version to use, then check that this works in a terminal:

   ```bash
   kaosctl lint --schema | head -3
   ```

   If it prints JSON, you are set. If it says the option is unknown, update kaos-lib.
2. Get the file `kaos-pipeline.vsix` from your platform team.
3. In VS Code: open the Extensions view, choose the `...` menu at the top, then **Install from VSIX...**, and pick the
   file. Or from a terminal:

   ```bash
   code --install-extension kaos-pipeline.vsix
   ```

4. Open your app folder. The extension turns on by itself when the folder has `.kaos/compat.yaml`,
   `.kubecore/dataset-config.yaml`, or a `pipeline.py` that imports `kubecore.authoring`. In any other folder it
   does nothing.

## Use it

| What | How |
| --- | --- |
| Suggestions | In `pipeline.py`, type inside `step(` and press `Ctrl+Space`. After `resumable=` it lists the allowed values. |
| Hover docs | Hold the mouse over an argument name or its value. |
| Findings | Save the file. Open the Problems view (`Ctrl+Shift+M`) to see all of them. |
| Quick fix | Put the cursor on a squiggle and press `Ctrl+.`. |
| Check now | `Ctrl+Shift+P`, then **KAOS: Check pipeline**. The full JSON report is written to the **KAOS** output panel. |
| Step graph | `Ctrl+Shift+P`, then **KAOS: Show step graph**. It refreshes when you save. |
| Sign in | `Ctrl+Shift+P`, then **KAOS: Sign in**. Your browser opens; finish there. **KAOS: Show sign-in status** tells you whether a session exists. |

The check reads files **as saved**. If you have unsaved changes the findings still describe the last save.

A check that needs facts about your project (your compute classes, the HPC (Slurm) time limits) is shown as
**skipped** until you give it your project's context file (see Settings). A skipped check is never a pass.

## Settings

| Setting | What it does |
| --- | --- |
| `kaos.kaosctlPath` | The `kaosctl` command. Default `kaosctl` (from your PATH). Set it in your **user** settings; a project folder cannot change it. |
| `kaos.contextFile` | Your project's `pipeline-context.yaml`, passed to the check as `--context`. A relative path is read from the project folder. |
| `kaos.checkDelayMs` | How long to wait after a save before checking (default 1000). |

## Sign-in

**KAOS: Sign in** runs `kaosctl login`: the browser sign-in with a one-time code exchange on a local address. The
extension never sees your token and never stores one. Before the first sign-in to an address, it shows you the address
the folder asks for and waits for your confirmation. Sign-in needs a folder you have marked as trusted.

## Troubleshooting

| You see | Do this |
| --- | --- |
| "kaosctl was not found" | Install kaos-lib, or set `kaos.kaosctlPath` in your user settings to the full path (for example `/home/me/.venv/bin/kaosctl`). |
| Suggestions look out of date | The extension uses the suggestions of the installed `kaosctl`, or a built-in copy if it cannot run it. Update kaos-lib, then run **KAOS: Reload step suggestions**. The **KAOS** output panel says which copy is in use. |
| No suggestions at all | Suggestions appear only inside a `step(` call in a file named `pipeline.py`. Open the **KAOS** output panel and check that the folder was recognised. |
| Nothing happens in my folder | The folder is not recognised as a KAOS pipeline folder (see Install, step 4). |
| "check did not run" in the status bar | Hover it for the reason; the **KAOS** output panel has the details. |
| Findings never change | They follow your last save. Save the file. |
| Sign-in does not open a browser | Run `kaosctl login` in a terminal in your app folder and read its message. |
| "Not signed in" after signing in | The status only says whether a session exists on this machine. If a command still says you are not signed in, sign in again. |
| The graph shows a dashed step | The step is created in a loop or a condition, so the file alone does not say where it goes. |

## What it does not do

It does not run your code or build images, and it has no dataset, model or run features yet. A clean check does not
prove that a pipeline is right: it reads your files without running them.

## Build the file yourself

For people who work on the extension (the folder `editors/vscode` of the kaos-lib repository):

```bash
npm install
npm test            # unit tests (no VS Code needed)
npm run test:integration -- /usr/share/code/code /path/to/kaosctl   # drives an installed VS Code; downloads nothing
npm run package     # writes dist/kaos-pipeline.vsix
```

The built-in suggestions copy is generated, not written by hand: `npm run schema:bundle` (needs `kaosctl`).
