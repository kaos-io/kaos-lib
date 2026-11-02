# Make your own dataset layout

A **layout** describes what a dataset holds: which files and folders, how a new dataset starts, what makes it
valid, and what a pipeline step downloads. kaos-lib ships two (`yolo` and `raw`); this guide makes a third one for
your own data, starting from a plain hera pipeline with no template.

The running example is a sound dataset: one `.wav` per clip under `clips/<split>/`, one `.json` with the clip's
labels next to it under `labels/<split>/`, and a `classes.yaml` naming the classes.

## 1. Write the layout

```bash
pip install kaos-lib
kaos-cli layout init ./sounds-layout --name sounds
```

`init` writes a starter `sounds-layout/layout.yaml` that already loads. Edit it into this:

```yaml
layout: 1                       # the spec version
name: sounds                    # the id: datasets made with it are labelled kaos.template=sounds
title: Sound clips
description: One .wav per clip and its labels as JSON, split into train and val.
version: "1"                    # your layout's own version, free form

parameters:                     # asked by `dataset create` and by the New dataset page
  - key: classes
    label: Class names
    type: list                  # list: one item per line; text: one line
    required: true
    form_key: classes           # where the value lives in form_file, so the dataset can be edited later
form_file: classes.yaml

skeleton:                       # what `create` writes; folders become <folder>/.keep
  folders: [clips/train, clips/val, labels/train, labels/val]
  files:
    classes.yaml: |
      classes:
      {{#each classes}}
        - {{@item|quote}}
      {{/each}}
    README.md: |
      # {{name}}

      {{#if description}}
      {{description}}

      {{/if}}
      {{classes|count}} classes. Put clips in `clips/<split>/` and their labels in `labels/<split>/`.

rules:                          # checked by kaos-cli and by kaos-lake
  required: [classes.yaml, "clips/train/*.wav", "clips/val/*.wav"]
  allowed: [README.md, classes.yaml, "clips/**", "labels/**"]
  extensions:
    - {files: "clips/**", allowed: [.wav]}
  pairs:
    - {files: "clips/**", needs: "labels/{stem}.json"}    # clips/train/a.wav needs labels/train/a.json
  manifests:
    - file: classes.yaml
      schema:
        type: object
        required: [classes]
        properties:
          classes: {type: array, minItems: 1, items: {type: string}}

materialize:                    # what a pull downloads (default: the whole tree)
  include: [classes.yaml, "clips/**", "labels/**"]
```

What the pieces mean:

- **Placeholders** in skeleton files: `{{name}}` (the dataset's repository name), `{{description}}`, `{{key}}` for a
  text parameter, `{{key|quote}}` (a double-quoted string, safe in YAML and JSON), `{{key|count}}` for a list,
  `{{#each key}} ... {{/each}}` with `{{@item}}` and `{{@index}}`, `{{#if key}} ... {{/if}}`. A line holding only a
  block tag disappears with its line break.
- **Patterns** are paths inside the dataset: `*` and `?` within one folder, `**` (a whole folder level) any depth.
  Files and folders starting with `.` are never looked at.
- **Rules**: `required` (each pattern matches at least one file), `allowed` (every file matches one of them),
  `extensions`, `pairs` (`{stem}` is the matched path below the pattern's fixed folders, without its
  extension), `lines` (every non-blank line of the matching files matches a regular expression; the syntax Go and
  Python share, so no lookaround and no backreferences), `manifests` (a YAML file checked against a small schema:
  `type`, `required`, `properties`, `additionalProperties`, `items`, `enum`, `minItems`/`maxItems`,
  `minProperties`/`maxProperties`, `minimum`/`maximum`, `minLength`/`maxLength`, `pattern`).

The whole spec is [`layout.schema.json`](../src/kaos_lib/layouts/shared/layout.schema.json). kaos-lake reads the
same schema and passes the same test fixtures, so a layout means the same thing in the CLI and in the web UI.

Check a folder against it before anything else:

```bash
kaos-cli layout show ./sounds-layout                    # the spec as kaos-lib read it
kaos-cli layout validate ./my-clips --layout ./sounds-layout
```

## 2. Share it with your project

```bash
kaos-cli login
kaos-cli layout publish ./sounds-layout
```

This opens a pull request adding `sounds/layout.yaml` to your project's `layouts` repository in lakeFS (created
the first time). Once it is merged, the New dataset page offers **Sound clips** next to the built-in layouts, and
everyone in the project can use the name `sounds`. A change is another `layout publish`; lakeFS keeps the history.
If kaos-lake cannot read a layout there, the New dataset page says why.

Prefer a package? Publish the folder with your Python package and declare it:

```toml
[project.entry-points."kaos_lib.layouts"]
sounds = "my_team.layouts:sounds"     # a layout.yaml path, a folder holding one, a module whose folder does, or a dict
```

Names are looked up built-in first, then installed packages, then the project's registry.

## 3. Create datasets with it

```bash
kaos-cli dataset create birds --layout sounds --classes robin,wren --description "Garden recordings"
kaos-cli dataset pull dataset-birds@latest ./birds      # the skeleton: add clips and labels
kaos-cli dataset push ./birds dataset-birds -m "first clips"   # validated against `sounds`, then a pull request
kaos-cli dataset release dataset-birds                  # v1, for pipelines
```

`push` validates with the layout the repository is labelled with; nothing is uploaded when the folder breaks a
rule. In the browser, the dataset's **Check layout** runs the same declarative rules on main.

## 4. Read them in a step

In a plain hera step, read the version the pipeline picked:

```python
from kaos_lib import datasets

ref = datasets.DatasetRef.parse(dataset)        # e.g. "dataset-birds@v1", the pipeline's dataset parameter
folder = datasets.materialize(ref)              # downloads classes.yaml, clips/, labels/ at that commit, cached
for wav in sorted((folder / "clips" / "train").glob("*.wav")):
    labels = folder / "labels" / "train" / (wav.stem + ".json")
    ...
```

`materialize` picks the layout from the repository's label, downloads only what `materialize.include` names, and
returns the folder. A second call for the same commit downloads nothing.

## 5. When rules are not enough: a hook

Some checks cannot be declared: the label JSON must name only classes from `classes.yaml`, say. Put them in a hook:

```python
# my_team/sounds_hook.py
import json, pathlib, yaml

def validate(root: pathlib.Path, layout) -> list:
    """Extra problems, after the declarative rules."""
    classes = set(yaml.safe_load((root / "classes.yaml").read_text())["classes"])
    problems = []
    for f in sorted((root / "labels").rglob("*.json")):
        for c in json.loads(f.read_text()).get("classes", []):
            if c not in classes:
                problems.append(f"{f.relative_to(root)}: unknown class {c}")
    return problems

def materialize(data_dir: pathlib.Path, out_dir: pathlib.Path, layout) -> pathlib.Path:
    """What materialize returns: here a file list your training code reads."""
    out = out_dir / "clips.txt"
    out.write_text("\n".join(str(p) for p in sorted(data_dir.glob("clips/**/*.wav"))))
    return out
```

and name it in the layout: `hook: my_team.sounds_hook`. Both functions are optional. `data_dir` holds the data
(the cache, or a staged copy), `out_dir` is where you may write.

Hooks run only in kaos-lib, where your package is installed: `layout validate`, `dataset push` and
`materialize`. kaos-lake never runs code from a layout; it checks the declarative rules only and says so. A project
layout whose hook package is not installed still works, with a warning that the hook's checks were skipped.

The built-in `yolo` layout is made the same way: [its layout.yaml](../src/kaos_lib/layouts/shared/builtin/yolo/layout.yaml)
declares the folders, the image to label pairing, the label line format and the `data.yaml` schema, and
[its hook](../src/kaos_lib/layouts/yolo.py) adds the class-id, value-count and coordinate checks and points
`data.yaml`'s `path:` at the downloaded copy.
