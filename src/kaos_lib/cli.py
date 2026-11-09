"""The ``kaosctl`` command line (``kubecore`` is a deprecated alias for one release).

    kaosctl login
    kaosctl dataset create|list|versions|release|push|pull|validate
    kaosctl dataset list --shared     datasets other projects share with yours (read-only)
    kaosctl upgrade                   install the kaos-lib the targeted platform recommends
    kaosctl --version                 version, release channel and the platform's recommendation
    kaosctl run --lock <mlflow-run-id> -- <command>   run a command reading exactly the commits that run read
    kaosctl layout list|show|init|validate|publish   dataset layouts (built-in, installed, the project's)
    kaosctl lint [folder]             check pipeline.py and its config without running it (no login, no network)

User errors print one ``ERROR:`` line (exit 1; validation problems exit 2), never a
traceback. Every successful command prints the next useful step and a link.
"""
from __future__ import annotations

import argparse
import datetime
import os
import pathlib
import subprocess
import sys
import types
from typing import Optional

import requests

from . import __version__, channel, credentials, datasets, layouts, peers, support
from .lint import cli as lint_cli
from .config import resolve_endpoint
from .errors import AuthError, DatasetError, KaosLibError, UnsupportedVersion, ValidationFailed
from .lakefs import LakeFS

EXIT_USER_ERROR, EXIT_INVALID_DATASET = 1, 2
WRITE_COMMANDS = {"create", "release", "push", "publish"}   # change data in lakeFS: refused when unsupported


def _connect(args) -> LakeFS:
    """Build the lakeFS client from --url / env / app config and the credential chain, then check support."""
    client = LakeFS.connect(getattr(args, "url", None))
    command = getattr(args, "dataset_command", None) or getattr(args, "layout_command", None)
    _support_gate(client, command in WRITE_COMMANDS)
    return client


def _url_client(args) -> Optional[LakeFS]:
    """A client for ``--url`` when given; otherwise None, and ``layouts.load`` connects only if it must."""
    return _connect(args) if getattr(args, "url", None) else None


def _maybe_connect(args) -> Optional[LakeFS]:
    """The project's lakeFS when one is configured and signed in to, else None (local layouts still work)."""
    try:
        return _connect(args)
    except (KaosLibError, requests.exceptions.ConnectionError) as exc:
        print(f"NOTE: the project's layouts were not looked up ({exc}).", file=sys.stderr)
        return None


def _support_gate(client: LakeFS, write: bool) -> None:
    """Warn when this kaos-lib is behind/deprecated/unsupported; refuse a write only when the platform says unsupported.

    The platform's metadata comes from the project lakeFS; without it (offline, older kaos-lake) the newest public
    release.json of this kaos-lib's channel is used, else the packaged ``_release.json``, and nothing is refused.
    """
    live = support.from_lakefs(client)
    fallback = None if live is not None else (
        channel.public_release(channel.channel_of_version(__version__)) or support.packaged())
    result = support.check(__version__, live if live is not None else fallback)
    if result["verdict"] == support.CURRENT:
        return
    fix = f" Fix: {result['fix']}" if result["fix"] else ""
    if write and live is not None and result["verdict"] == support.UNSUPPORTED:
        raise UnsupportedVersion(f"{result['message']}; commands that change data are refused.{fix}")
    print(f"WARNING: {result['message']}.{fix}", file=sys.stderr)


def _repo_url(c: LakeFS, repo: str, tail: str = "objects") -> str:
    return f"{c.base_url}/repositories/{repo}/{tail}"


def _print_errors(errors: list) -> None:
    print(layouts.ValidationReport(errors).format(), file=sys.stderr)


def _values(args, layout: layouts.Layout) -> dict:
    """Parameter values from ``--param key=value`` (list items comma-separated) and ``--classes``."""
    pairs = list(getattr(args, "param", None) or [])
    if getattr(args, "classes", None):
        pairs.append(f"classes={args.classes}")
    params = {p["key"]: p for p in layout.parameters}
    values: dict = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        key = key.strip()
        if not sep or key not in params:
            known = ", ".join(params) or "none"
            raise DatasetError(f"layout {layout.name} has no parameter {key!r} (its parameters: {known}); "
                               "write --param <key>=<value>.")
        values[key] = [x.strip() for x in value.split(",")] if params[key]["type"] == "list" else value
    return values


# ------------------------------------------------------------------ commands
def cmd_login(args) -> int:
    url = resolve_endpoint(args.url)
    credentials.browser_login(url)
    print("Next: kaosctl dataset list")
    return 0


def _repo(c: LakeFS, name: str) -> str:
    """An existing repository by its exact name, else the ``dataset-<name>`` shorthand."""
    return name if c.repository(name) else datasets.dataset_repo(name)


def cmd_create(args) -> int:
    datasets.refuse_shared(args.name, "create")
    if args.layout == datasets.NO_TEMPLATE and (args.classes or args.param):
        raise datasets.DatasetError("--classes and --param fill a layout's parameters, and no layout is named "
                                    "(the default is none): add --layout yolo, or another from `kaosctl layout list`")
    c = _connect(args)
    if args.layout == datasets.NO_TEMPLATE:
        repo = datasets.create_dataset(args.name, datasets.NO_TEMPLATE, args.description or "", c)
        print(f"Created {repo}: empty, no layout (labelled kaos.kind=dataset).")
        print(f"  Open it:  {_repo_url(c, repo)}")
        print("kaos-lake lists it as a dataset once its first commit lands. Next: push your files")
        print(f"  kaosctl dataset push ./my-files {repo} -m \"first files\"")
        return 0
    layout = layouts.load(args.layout, c)
    repo = datasets.create_dataset(args.name, layout, args.description or "", c, _values(args, layout))
    print(f"Created {repo} (layout {layout.name}).")
    print(f"  Open it:  {_repo_url(c, repo)}")
    print("Next: get a local copy, add your files, then push (opens a pull request):")
    print(f"  kaosctl dataset pull {repo}@latest ./{repo}")
    print(f"  kaosctl dataset push ./{repo} {repo} -m \"add data\"")
    return 0


def cmd_list_shared(args) -> int:
    c = _connect(args)
    answers = peers.shared(c)
    rows = [r for a in answers for r in a.datasets]
    for a in answers:
        if a.note:
            print(f"NOTE: {a.peer}: {a.note}; nothing listed from it.", file=sys.stderr)
    if not rows:
        print("No datasets are shared with your project yet. The owner shares one from its dataset page in lakeFS.")
        return 0
    names = [f"{r.owner}/{r.repo}" for r in rows]
    width = max(len(n) for n in names)
    for name, r in zip(names, rows):
        print(f"{name:<{width}}  {', '.join(r.versions) or 'no versions':<12}  {r.description}")
    pick = next(((n, r) for n, r in zip(names, rows) if r.versions), None)
    if pick:
        print(f"Pick one in the pipeline:  dataset = {pick[0]}@{pick[1].versions[0]}")
        print(f"Or download it:  kaosctl dataset pull {pick[0]}@{pick[1].versions[0]}")
    else:
        print(f"Next: kaosctl dataset pull {names[0]}@{datasets.LATEST}")
    return 0


def cmd_list(args) -> int:
    if args.shared:
        return cmd_list_shared(args)
    rows = datasets.list_datasets(_connect(args))
    if not rows:
        print("No datasets yet. Create one with: kaosctl dataset create <name> [--layout <layout>] "
              "(see kaosctl layout list)")
        return 0
    width = max(len(r.repo) for r in rows)
    for r in rows:
        flags = "  [default]" if r.default else ""
        print(f"{r.repo:<{width}}  {r.template or '-':<12}  {r.description}{flags}")
    print(f"Next: kaosctl dataset versions {rows[0].repo}")
    return 0


def cmd_versions(args) -> int:
    owner, name = datasets.split_owner(args.repo)
    c = _connect(args)
    if owner:   # a dataset another project shares: no lookup in the own lakeFS
        repo = f"{owner}/{name}"
    else:
        repo = _repo(c, args.repo)
    found = datasets.versions(repo, c)
    print(f"{repo}: {', '.join(found) if found else 'no versions yet'} (and {datasets.LATEST}, the head of main)")
    if found:
        print(f"Pick one in the pipeline:  dataset = {repo}@{found[-1]}")
    elif owner:
        print(f"Next: ask project {owner} to release a version, or pick  dataset = {repo}@{datasets.LATEST}")
    else:
        print(f"Next: kaosctl dataset release {repo}")
    return 0


def cmd_release(args) -> int:
    datasets.refuse_shared(args.repo, "release")
    c = _connect(args)
    repo = _repo(c, args.repo)
    version = datasets.release(repo, c)
    print(f"Released {repo} {version}.")
    print(f"  Open it:  {_repo_url(c, repo, f'objects?ref={version}')}")
    print(f"Pick it in the pipeline:  dataset = {repo}@{version}")
    return 0


def cmd_push(args) -> int:
    datasets.refuse_shared(args.repo, "push to")
    c = _connect(args)
    repo = _repo(c, args.repo)
    layout = layouts.load(args.layout or datasets.layout_of(repo, c), c)   # no known label: raw, checks nothing
    if args.no_validate:
        print("WARNING: --no-validate: the dataset was not validated; reading it may fail on bad files.",
              file=sys.stderr)
    result = layout.publish(
        args.dir, repo, args.message, description=args.description or "",
        validate_first=not args.no_validate, client=c)
    if result.created:
        print(f"Created {repo}.")
    print(f"Uploaded to draft branch {result.branch} and opened a pull request into main.")
    print(f"  Review and merge it:  {result.pull_url}")
    print(f"Next: after merging, run  kaosctl dataset release {repo}")
    return 0


def cmd_pull(args) -> int:
    c = _connect(args)
    ref = datasets.DatasetRef.parse(args.ref)
    path = datasets.materialize(ref, args.dest, args.layout, c, prefix=args.prefix)
    print(f"Ready: {path}")
    if path.is_dir():
        print(f"Next: your files are in {path}; read them from there in your code.")
    else:
        print(f"Next: hand {path} to your code (it is the layout's entry file).")
    return 0


def cmd_validate(args) -> int:
    layout = layouts.load(args.layout, _url_client(args))
    report = layout.validate(args.dir)
    hook = f", and its hook {layout.spec['hook']}" if layout.spec.get("hook") else ""
    if report.ok:
        print(f"{args.dir} is a valid {layout.name} dataset (the layout's rules{hook}).")
        print("Next: kaosctl dataset push <dir> <dataset-repo> -m \"message\"")
        return 0
    print(f"{args.dir} has {len(report.errors)} problem(s) for layout {layout.name}:", file=sys.stderr)
    print(report.format(), file=sys.stderr)
    return EXIT_INVALID_DATASET


def _platform_support(url: Optional[str] = None):
    """(platform base URL, its kaos_lib_support value or None). Signed out: the same read without a credential."""
    try:
        client = LakeFS.connect(url)
    except AuthError:
        client = types.SimpleNamespace(base_url=resolve_endpoint(url), session=requests.Session())
    return client.base_url, support.from_lakefs(client)


def version_text() -> str:
    """Two lines: the version and channel, then what the targeted platform recommends."""
    first = f"kaosctl {__version__} ({channel.describe(channel.installed(__version__))})"
    try:
        base, value = _platform_support()
    except KaosLibError as exc:
        return f"{first}\nplatform: unknown ({exc})"
    rec = channel.recommended(value)
    return f"{first}\nplatform {base}: " + (f"recommends kaos-lib {rec}" if rec else "publishes no recommendation yet")


class _VersionAction(argparse.Action):
    def __init__(self, option_strings, dest=argparse.SUPPRESS, default=argparse.SUPPRESS, help=None):
        super().__init__(option_strings=option_strings, dest=dest, default=default, nargs=0, help=help)

    def __call__(self, parser, namespace, values, option_string=None):
        print(version_text())
        parser.exit()


def cmd_upgrade(args) -> int:
    """Install the kaos-lib spec the targeted platform recommends (its lakeFS ``/kaos/v1/ui``), else the newest
    release of this install's channel (the public release.json)."""
    try:
        base, value = _platform_support(getattr(args, "url", None))
        rec, where = channel.recommended(value), f"the platform at {base}"
    except KaosLibError as exc:
        rec, where = None, f"no platform ({exc})"
    if not rec:
        mine = channel.channel_of_version(__version__)
        newest = channel.public_release(mine if mine in channel.PREFIX else "stable") or {}
        rec = channel.recommended(newest)
        if not rec:
            print(f"ERROR: {where} publishes no recommended kaos-lib, and no {mine} release is published yet "
                  f"(index: {channel.INDEXES.get(mine, channel.INDEXES['stable'])}); nothing was installed.",
                  file=sys.stderr)
            return EXIT_USER_ERROR
        print(f"NOTE: {where} publishes no recommended kaos-lib; using the newest {newest.get('channel', mine)} "
              f"release {newest.get('tag', '')}.", file=sys.stderr)
        base = newest.get("index_url") or "the public channel"
    req = channel.requirement(rec, channel.has_zitadel_extra())
    print(f"{base} recommends {req}")
    if channel.is_current(req, channel.installed(__version__), __version__):
        print(f"kaos-lib {__version__} is already that; nothing to do.")
        return 0
    cmd = channel.pip_command(req)
    if args.dry_run:
        print("would run: " + " ".join(cmd))
        return 0
    code = subprocess.call(cmd)
    if code:
        raise KaosLibError(f"pip install failed (exit {code}); kaos-lib {__version__} is unchanged")
    print("Next: kaosctl --version")
    return 0


def cmd_run(args) -> int:
    from . import lock
    from .mlflow import mlflow
    command = args.cmd[1:] if args.cmd[:1] == ["--"] else args.cmd
    if not command:
        raise KaosLibError("nothing to run: write kaosctl run --lock <mlflow-run-id> -- <command> [args...].")
    data_lock = lock.load(args.lock, mlflow())
    print(f"Replaying the data lock of MLflow run {args.lock}:", file=sys.stderr)
    for r in data_lock.reads:
        print(f"  {r.owner + '/' if r.owner else ''}{r.repo}@{r.ref} -> {r.commit}", file=sys.stderr)
    try:
        return subprocess.call(command, env={**os.environ, lock.ENV: data_lock.to_json()})
    except OSError as exc:
        raise KaosLibError(f"cannot run {command[0]!r}: {exc.strerror or exc}.") from None


def cmd_layout_list(args) -> int:
    rows = layouts.available(_maybe_connect(args))
    width = max(len(r.name) for r in rows)
    for r in rows:
        hook = "  (hook)" if r.spec.get("hook") else ""
        print(f"{r.name:<{width}}  {r.source:<9}  {r.title}{hook}")
    print("Next: kaosctl layout show <name>, or make your own: kaosctl layout init ./my-layout")
    return 0


def cmd_layout_show(args) -> int:
    import yaml
    layout = layouts.load(args.name, _url_client(args))
    print(f"# {layout.name}: {layout.source} ({layout.origin})")
    print(yaml.safe_dump(layout.spec, sort_keys=False, allow_unicode=True, width=100), end="")
    return 0


STARTER = """# A dataset layout (kaos-lib layouts, spec version 1). Check it with
#   kaosctl layout validate <a dataset folder> --layout {dir}
# and share it with your project with  kaosctl layout publish {dir}
layout: 1
name: {name}
title: {title}
description: What datasets in this layout hold.
version: "1"
parameters:
  - key: classes
    label: Class names
    type: list
    required: true
    help: One per line.
skeleton:
  folders: [data]
  files:
    classes.txt: |
      {{{{#each classes}}}}
      {{{{@item}}}}
      {{{{/each}}}}
    README.md: |
      # {{{{name}}}}

      {{{{#if description}}}}
      {{{{description}}}}

      {{{{/if}}}}
      Files go in `data/`, one `<id>.json` per sample; `classes.txt` lists the {{{{classes|count}}}} classes.
rules:
  required: [classes.txt, "data/*.json"]
  allowed: [README.md, classes.txt, "data/*.json"]
  lines:
    - files: classes.txt
      pattern: '[A-Za-z0-9_ -]+'
      message: one class name per line
materialize:
  include: [classes.txt, "data/**"]
"""


def cmd_layout_init(args) -> int:
    import yaml
    target = pathlib.Path(args.dir)
    out = target / "layout.yaml"
    if out.exists():
        raise DatasetError(f"{out} already exists; edit it, or pick another folder.")
    name = args.name or target.resolve().name.lower()
    shown = args.dir if "/" in args.dir else f"./{args.dir}"   # a name without / would be looked up, not read
    if args.from_layout:
        spec = dict(layouts.load(args.from_layout, _url_client(args)).spec)
        spec["name"] = name
        text = yaml.safe_dump(spec, sort_keys=False, allow_unicode=True, width=100)
    else:
        text = STARTER.format(name=name, title=name.replace("-", " ").capitalize(), dir=shown)
    layouts.spec.parse(text, str(out))   # refuse to write a layout that would not load
    target.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    print(f"Wrote {out}. Edit it, then check a dataset folder with it:")
    print(f"  kaosctl layout validate <folder> --layout {shown}")
    print(f"Share it with your project:  kaosctl layout publish {shown}")
    return 0


def cmd_layout_publish(args) -> int:
    path = pathlib.Path(args.path)
    spec = layouts.spec.read(path)
    name = spec["name"]
    if name in layouts.builtin_names():
        raise DatasetError(f"{name} is a built-in layout; give yours another name.")
    c = _connect(args)
    repo = layouts.LAYOUTS_REPOSITORY
    datasets.ensure_repository(c, repo, {})
    branch = "layout-" + name + "-" + datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
    c.create_branch(repo, branch, datasets.MAIN)
    c.upload_object(repo, branch, f"{name}/layout.yaml", path / "layout.yaml" if path.is_dir() else path)
    message = args.message or f"Layout {name}"
    head = c.branch_commit(repo, branch)
    if c.commit(repo, branch, message, tolerate_empty=True) == head:
        c.delete_branch(repo, branch)
        print(f"{name} is already the project's version; nothing to publish.")
        return 0
    pull = c.create_pull(repo, branch, datasets.MAIN, message)
    if spec.get("hook"):
        print(f"NOTE: kaos-lake never runs hooks: {spec['hook']} runs only where its package is installed.",
              file=sys.stderr)
    print(f"Opened a pull request adding {name}/layout.yaml to the project's {repo} repository.")
    print(f"  Review and merge it:  {c.base_url}/repositories/{repo}/pulls/{pull}")
    print(f"Once merged, the New dataset page and  kaosctl dataset create <name> --layout {name}  offer it.")
    return 0


# ------------------------------------------------------------------ parser
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="kaosctl", description="KAOS platform tools: datasets and run outputs.")
    p.add_argument("--version", action=_VersionAction, help="show the version, channel and platform recommendation")
    sub = p.add_subparsers(dest="command", required=True)

    def add(parent, name, func, help_, url=True):
        sp = parent.add_parser(name, help=help_, description=help_)
        if url:
            sp.add_argument("--url", help="lakeFS URL (default: LAKEFS_ENDPOINT or .kubecore/dataset-config.yaml)")
        sp.set_defaults(func=func)
        return sp

    add(sub, "login", cmd_login, "sign in through the browser")
    add(sub, "upgrade", cmd_upgrade, "install the kaos-lib the targeted platform recommends").add_argument(
        "--dry-run", action="store_true", help="print the pip command instead of running it")
    ds = sub.add_parser("dataset", help="create, version, push and pull datasets")
    dsub = ds.add_subparsers(dest="dataset_command", required=True)
    layout_help = "a layout name (kaosctl layout list) or a path to a layout.yaml or its folder"

    sp = add(dsub, "create", cmd_create, "create a new dataset repository from a layout")
    sp.add_argument("name", help="dataset name (the repository becomes dataset-<name>)")
    sp.add_argument("--layout", "--template", dest="layout", default=datasets.NO_TEMPLATE,
                    help=f"{layout_help}; none for an empty repository (default none)")
    sp.add_argument("--param", action="append", metavar="KEY=VALUE",
                    help="a layout parameter; list items comma-separated (repeat for more)")
    sp.add_argument("--classes", help="shortcut for --param classes=a,b,c (the yolo layout)")
    sp.add_argument("--description", help="what the dataset is for")
    add(dsub, "list", cmd_list, "list the datasets you can read").add_argument(
        "--shared", action="store_true", help="list the datasets other projects share with yours (read-only)")
    add(dsub, "versions", cmd_versions, "list a dataset's versions").add_argument("repo")
    add(dsub, "release", cmd_release, "tag the head of main with the next version").add_argument("repo")
    sp = add(dsub, "push", cmd_push, "validate a local folder and open a pull request into the dataset")
    sp.add_argument("dir")
    sp.add_argument("repo", help="dataset repository (created if missing)")
    sp.add_argument("-m", "--message", required=True, help="what changed (pull request title)")
    sp.add_argument("--description", help="description label when the repository is created")
    sp.add_argument("--no-validate", action="store_true", help="skip the layout's checks (prints a warning)")
    sp.add_argument("--layout", "--format", dest="layout",
                    help=f"{layout_help} (default: the repository's kaos.template label, else raw)")
    sp = add(dsub, "pull", cmd_pull, "download a dataset version")
    sp.add_argument("ref", help="<repository>@<ref>, e.g. dataset-default@v2, my-repo@main "
                                "or <project>/dataset-x@v1 (shared with your project)")
    sp.add_argument("dest", nargs="?", help="folder to download into (default: a per-commit cache)")
    sp.add_argument("--layout", "--format", dest="layout",
                    help=f"{layout_help} (default: the repository's label, else raw)")
    sp.add_argument("--prefix", help="download only this folder of the repository (layouts that download all)")
    sp = add(dsub, "validate", cmd_validate, "check a local folder against a layout (same as layout validate)")
    sp.add_argument("dir")
    sp.add_argument("--layout", "--format", dest="layout", default="yolo", help=f"{layout_help} (default yolo)")

    sp = add(sub, "run", cmd_run, "run a command with the dataset commits an earlier MLflow run read", url=False)
    sp.add_argument("--lock", required=True, metavar="MLFLOW_RUN_ID",
                    help="the MLflow run whose data.lock.json to replay (exported to the command as $KAOS_LIB_LOCK)")
    sp.add_argument("cmd", nargs=argparse.REMAINDER, metavar="-- command", help="the command to run, after --")

    ly = sub.add_parser("layout", help="dataset layouts: list, show, make your own, check a folder, publish")
    lsub = ly.add_subparsers(dest="layout_command", required=True)
    add(lsub, "list", cmd_layout_list, "the layouts you can use: built-in, installed, the project's")
    add(lsub, "show", cmd_layout_show, "print a layout's spec").add_argument("name", help=layout_help)
    sp = add(lsub, "init", cmd_layout_init, "write a starter layout.yaml to make your own layout")
    sp.add_argument("dir", help="folder for the new layout.yaml")
    sp.add_argument("--name", help="the layout's name (default: the folder's name)")
    sp.add_argument("--from", dest="from_layout", help="start from a copy of this layout")
    sp = add(lsub, "validate", cmd_validate, "check a local dataset folder against a layout")
    sp.add_argument("dir")
    sp.add_argument("--layout", required=True, help=layout_help)
    sp = add(lsub, "publish", cmd_layout_publish, "share a layout with your project (a pull request into "
                                                  f"its {layouts.LAYOUTS_REPOSITORY} repository)")
    sp.add_argument("path", help="a layout.yaml or its folder")
    sp.add_argument("-m", "--message", help="pull request title")

    sp = sub.add_parser("lint", help="check pipeline.py and its config without running it",
                        description="Check a pipeline's pipeline.py and the files around it for problems the platform "
                                    "would refuse or that usually go wrong later. It reads your files and never runs "
                                    "them; it needs no login and no network. Exit 0: no errors; 2: errors found.")
    lint_cli.add_arguments(sp)
    sp.set_defaults(func=lint_cli.run)
    return p


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ValidationFailed as exc:
        print("ERROR: the dataset is not valid, nothing was uploaded:", file=sys.stderr)
        _print_errors(exc.errors)
        return EXIT_INVALID_DATASET
    except KaosLibError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_USER_ERROR
    except requests.exceptions.ConnectionError as exc:
        print(f"ERROR: cannot reach lakeFS ({exc.__class__.__name__}). Check --url / "
              ".kubecore/dataset-config.yaml and your network.", file=sys.stderr)
        return EXIT_USER_ERROR


def kubecore_alias(argv: Optional[list] = None) -> int:
    """The ``kubecore`` command: a deprecated alias of ``kaosctl``, kept for one release."""
    print("NOTE: `kubecore` is now `kaosctl`; the `kubecore` command goes away in the next release.",
          file=sys.stderr)
    return main(argv)


def kaos_cli_alias(argv: Optional[list] = None) -> int:
    """The ``kaos-cli`` command: a hidden alias of ``kaosctl`` (not in the help or the docs), kept for one release."""
    print("NOTE: `kaos-cli` is now `kaosctl`; the `kaos-cli` command goes away in the next release.",
          file=sys.stderr)
    return main(argv)


if __name__ == "__main__":
    sys.exit(main())
