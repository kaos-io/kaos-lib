# KAOS Pipelines for VS Code

Helps you write and check the `pipeline.py` of a KAOS ML pipeline:

- **Suggestions and docs** while you type a `step(...)` call: argument names, allowed values and a short explanation
  of each. Hover an argument to read about it.
- **Checks as you save.** The same check the pull request runs (`kaosctl lint`) shows its findings as squiggles in
  the file, each with a fix hint and a link to its page.
- **A step graph.** A read-only picture of your steps and what each one needs. Click a step to jump to its line.
- **Sign-in** with the same browser sign-in as `kaosctl login`.

The extension reads your files; it never runs your pipeline or your step code.

## Install

1. Install `kaosctl` (it comes with the `kaos-lib` package). See the kaos-lib installation page for the index and the
   version to use, then check that this works in a terminal:

   ```bash
   kaosctl lint --schema | head -3
   ```

   If it prints JSON, you are set. If it says the option is unknown, update kaos-lib (`kaosctl upgrade`).
2. Install the extension that was published with your kaos-lib:

   ```bash
   kaosctl vscode install
   ```

   It downloads the extension of the same version as your `kaosctl`, checks the file, and installs it into the first
   of `code`, `cursor`, `codium`, `code-insiders` it finds. Use `--editor <command or path>` to pick one, and
   `--dry-run` to see what it would do. If it says the editor's command was not found, run
   **Shell Command: Install 'code' command in PATH** from the VS Code Command Palette first.

   To install by hand instead: `kaosctl vscode install --download .` saves the checked `.vsix` file; then in VS Code
   open the Extensions view, choose the `...` menu, **Install from VSIX...**, and pick the file.
3. Reload the window (Command Palette: **Developer: Reload Window**).
4. Open your app folder. The extension turns on by itself when the folder has `.kaos/compat.yaml`,
   `.kubecore/dataset-config.yaml`, or a `pipeline.py` that imports `kubecore.authoring`. In any other folder it
   does nothing.

## Update

The extension and `kaosctl` are released together and carry the same version. After you update kaos-lib
(`kaosctl upgrade`), the extension notices on the next start that it no longer matches and offers **Update**: it
installs the matching version and asks you to reload the window. **Not now** stops the question for that version.

You can also ask at any time with **KAOS: Check for an extension update**, or run `kaosctl vscode install` again.
An editor never updates an extension installed from a file by itself, so one of these is how you get a new one.

## Use it

| What | How |
| --- | --- |
| Suggestions | In `pipeline.py`, type inside `step(` and press `Ctrl+Space`. After `resumable=` it lists the allowed values. |
| Hover docs | Hold the mouse over an argument name or its value. |
| Findings | Type or save. Open the Problems view (`Ctrl+Shift+M`) to see all of them. |
| Check now | `Ctrl+Shift+P`, then **KAOS: Check pipeline**. The full JSON report is written to the **KAOS** output panel. |
| Step graph | `Ctrl+Shift+P`, then **KAOS: Show step graph**. It refreshes when you save. |
| Sign in | `Ctrl+Shift+P`, then **KAOS: Sign in**. Your browser opens; finish there. **KAOS: Show sign-in status** tells you whether a session exists. |

The check follows what you type in `pipeline.py`, a moment after you stop typing, without saving. Your other files
(`config/`, your step folders) are read as saved.

A check that needs facts about your project (your compute classes, the HPC (Slurm) time limits) is shown as
**skipped** (listed in the status bar tooltip; the KAOS output panel prints them once) until you give it your project's context file (see Settings). A skipped check is never a pass.

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
| "no VS Code extension is published for kaos-lib ..." | Your kaos-lib is not a published release, or is older than the first published extension. Run `kaosctl upgrade`, then `kaosctl vscode install`. |
| The update is offered again after "Not now" | It is asked once per new version. A newer kaos-lib brings a newer extension. |
| "check did not run" in the status bar | Hover it for the reason; the **KAOS** output panel has the details. |
| Findings do not change when you edit another file | Only `pipeline.py` is checked as you type; other files are read as saved. Save them. |
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
