# Add or change data

**You want** to add files to a dataset you uploaded, or change them, and have your pipeline read the new files.

This is for an uploaded dataset, `dataset-<name>`. A dataset a step makes is changed by the step that makes it
([the three kinds of dataset](data-contract.md#what-a-dataset-is)).

1. **Sign in**, inside your app folder: `kaosctl login`.
2. **Get the current files** into a new folder. Skip this for a new dataset.

    ```bash
    kaosctl dataset pull dataset-cats@latest ./cats
    ```

3. **Change the folder.** Add files, change files, delete files.
4. **Push the folder.** `push` makes the dataset equal to the folder: it uploads the files that are new or different, and
   it removes from the dataset every file the folder no longer has. A dataset that does not exist yet is created.

    ```bash
    kaosctl dataset push ./cats dataset-cats -m "40 more labelled images"
    ```

    `push` first checks the files against the dataset's layout and lists every problem. It does not change the
    dataset yet. It opens a pull request and prints the link. A folder that equals the dataset is refused:
    `nothing to publish: ... is identical to dataset-cats main.`
5. **Merge the pull request.** Open the link and press the merge button. A dataset changes only through a merged
   pull request. When it is merged, `latest` points to the new files.
6. **Release a version**, if a pipeline should read these files by a fixed name
   ([Release a dataset version](release-a-version.md)). Without it, a pipeline that leaves the version out reads `latest`.

## What a run that already started sees

It sees the files it started with. When a run starts, the platform fixes every dataset it reads to one exact version.
Every step reads that version, even if you merge a change while the run is going
([fixed when the run starts](data-reads.md#fixed-when-the-run-starts)).

- A run that reads `latest` and starts after the merge reads the new files.
- A run that reads `dataset-cats@v2` reads the files of `v2` until someone changes the setting, whatever you push.
- A run that starts from a step of an earlier run keeps the version that run read
  ([Re-running](rerun.md)).

To read the new files in a run, start a new run.

Next: [Release a dataset version](release-a-version.md). The commands are in the [Reference](reference.md#commands).
