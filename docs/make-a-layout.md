# Make a dataset layout

**You want** a kind of dataset of your own, with the files it starts with and the rules every push is checked against: the
way the built-in `yolo` layout does it for images and labels ([layouts](reference.md#dataset-layouts)).

`kaosctl layout init ./sounds-layout --name sounds` writes a starter `layout.yaml` that already loads. This one describes a
sound dataset: one `.wav` per clip under `clips/<split>/`, its labels as JSON under `labels/<split>/`, and a `classes.yaml`.

```yaml title="sounds-layout/layout.yaml"
--8<-- "examples/layout/layout.yaml"
```

- Placeholders in skeleton files: `{{name}}`, `{{description}}`, `{{key}}` for a text parameter, `{{key|quote}}`,
  `{{key|count}}` for a list, `{{#each key}} ... {{/each}}` with `{{@item}}` and `{{@index}}`, `{{#if key}} ... {{/if}}`.
- Patterns are paths inside the dataset: `*` and `?` within one folder, `**` any depth. Names starting with `.` are never read.
- Rules: `required`, `allowed`, `extensions`, `pairs` (`{stem}` is the matched path without its extension), `lines` (a regular
  expression every non-blank line must match) and `manifests` (a YAML file checked against a small schema).

```bash
kaosctl layout show ./sounds-layout
kaosctl layout validate ./my-clips --layout ./sounds-layout
kaosctl layout publish ./sounds-layout
kaosctl dataset create birds --layout sounds --classes robin,wren
```

`publish` opens a pull request that adds the layout to your project's layouts; once it is merged, everyone in the project can
use the name `sounds`.
