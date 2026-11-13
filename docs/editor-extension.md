# Use the editor extension

**You want** to see your pipeline's mistakes while you type, and to see its steps as a picture, in VS Code.

The KAOS extension for VS Code (the extension is called `kaos-pipeline`) works on `pipeline.py` in your app folder:

- **The step schema.** Type inside a `step(` call and press `Ctrl+Space`: you get the argument names, the allowed
  values and a short explanation of each. Hover an argument to read about it.
- **Lint in the editor.** The same check as `kaosctl lint` runs a moment after you stop typing. Each finding shows as a
  squiggle in `pipeline.py`, with a fix hint and a link to its page ([Lint checks](lint.md)).
- **The graph.** `Ctrl+Shift+P`, then **KAOS: Show step graph** draws your steps and what each one needs. Click a step
  to jump to its line.

The extension only reads your files. It never runs your pipeline or your step code, and a clean check does not prove
that a pipeline is right.

## Install it

You need `kaosctl` first (it comes with the `kaos-lib` package) and VS Code, or Cursor, Codium or VS Code Insiders.

```bash
kaosctl vscode install
```

The command downloads the extension that belongs to your `kaosctl`, checks the file, and installs it into the first
editor it finds, looking for `code`, `cursor`, `codium` and `code-insiders` in that order. Then reload the editor
window (`Ctrl+Shift+P`, then **Developer: Reload Window**).

- `--editor <command or path>` picks the editor yourself.
- `--dry-run` shows what the command would download and run, and changes nothing.
- If it says the editor's command was not found, open the Command Palette in VS Code and run
  **Shell Command: Install 'code' command in PATH**, then try again.

Open your app folder. The extension turns on by itself when the folder has `.kaos/compat.yaml`, or a `pipeline.py` that
imports `kubecore.authoring` (the template's does). In other folders it does nothing.

If it says that no extension is published for your kaos-lib, your install is not a published release, or it is older
than the first release that has the extension. Run `kaosctl upgrade`, then `kaosctl vscode install` again.

## Upgrade it

The extension has the same version as your `kaos-lib`. Upgrade in two steps:

1. Upgrade the library: `kaosctl upgrade`.
2. Upgrade the extension: `kaosctl vscode install`.

`kaosctl upgrade` does not touch the extension. It only reminds you to run the second command.
`kaosctl vscode install` always installs the extension of the kaos-lib you have now, not the newest one that exists.
Run it again after each `kaosctl upgrade`.

The editor does not update this extension for you. The extension does check itself: when it starts, it compares its
version with your `kaosctl`, and if they differ it offers **Update**. **Not now** stops the question for that version.
You can ask at any time with `Ctrl+Shift+P`, then **KAOS: Check for an extension update**.

## Check the version

Which extension version is installed:

```bash
code --list-extensions --show-versions | grep kaos-pipeline
```

(Use your editor's command in place of `code`.) The Extensions view in the editor shows the same version.

Which version it should be:

```bash
kaosctl --version
```

For kaos-lib `0.4.0` the extension is `0.4.0`. For a release candidate such as `0.4.0rc7` it is `0.4.0-rc.7`. If the
two do not match, run `kaosctl vscode install`.

## Remove it

```bash
code --uninstall-extension kaos-io.kaos-pipeline
```

or open the Extensions view, find **KAOS Pipelines**, and choose **Uninstall**.

## Offline, or an editor with no command line

`kaosctl vscode install` needs the internet: it reads the release's record and downloads the file. On a machine that
has no access, do the download where you have it:

```bash
kaosctl vscode install --download .
```

This saves the checked `.vsix` file in the folder you name and prints its path. Copy the file to the other machine,
then install it with `code --install-extension <file>.vsix`, or in VS Code open the Extensions view, choose the `...`
menu, **Install from VSIX...**, and pick the file.

Once it is installed, the extension needs no internet. It does need `kaosctl` on the same machine. If it cannot run
`kaosctl`, set `kaos.kaosctlPath` in your user settings to its full path. Without a working `kaosctl`, the extension
cannot check your pipeline.

## When something does not work

| You see | Do this |
| --- | --- |
| "kaosctl was not found" | Install kaos-lib, or set `kaos.kaosctlPath` in your user settings. |
| Nothing happens in my folder | The folder is not recognised as an app folder: it needs `.kaos/compat.yaml`, or a `pipeline.py` that imports `kubecore.authoring`, at its top. |
| Suggestions look out of date | Upgrade both (see above), then run **KAOS: Reload step suggestions**. |
| A check is shown as skipped | It needs facts about your project. A skipped check is never a pass. |

Next: [Lint checks](lint.md) lists every check the editor shows.
