"""Generate the pages of the documentation site that must never drift from the code or the releases.

Run by the mkdocs hook `docs/hooks.py` on every build (so `mkdocs build` alone keeps them current), or by hand:
`python docs_gen.py docs`. It writes, under `<docs>/generated/`:

- `cli.md`: every `kaosctl` command's `--help`, taken from the argparse parser itself (`kaos_lib.cli.build_parser`);
- `built.md`: the kaos-lib version and commit this site was built from;
- `install.md`: the install command of each channel's newest release, from its public `release.json`.

The release metadata is read over the network; when it cannot be read the page says so instead of failing the
build, because the docs of a pull request must build offline as well.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import urllib.error
import urllib.request
from typing import Callable, Optional

BUCKET = os.environ.get("KAOS_LIB_RELEASE_BUCKET", "https://storage.googleapis.com/kaos-dev-511509-kaos-lib")
CHANNELS = (("prerelease", "rc", "published on every merge to `main`"),
            ("stable", "stable", "published only by the platform's release train, from an rc that passed the dev e2e"))
MISSING = "missing"   # the channel has no release.json (HTTP 404): nothing published yet
PYPI = "https://pypi.org/simple/"


def _subparsers(parser: argparse.ArgumentParser):
    for action in parser._actions:  # argparse keeps subcommands in a private action; this is the documented way
        if isinstance(action, argparse._SubParsersAction):
            return action
    return None


def _walk(parser: argparse.ArgumentParser, path: list):
    """(command path, parser) for the parser and every subcommand below it, in definition order."""
    yield path, parser
    sub = _subparsers(parser)
    if sub is None:
        return
    for name, child in sub.choices.items():
        yield from _walk(child, path + [name])


def cli_reference(parser: argparse.ArgumentParser) -> str:
    """Markdown with one section per command: its `--help` text, exactly as the command prints it."""
    out = ["# CLI reference", "",
           "Generated from the `kaosctl` parser on every build of this site, so it always matches the release "
           "it documents. `kaos-cli` is a hidden alias of `kaosctl` for one release (it prints a notice) and "
           "`kubecore` a deprecated one.", ""]
    for path, p in _walk(parser, ["kaosctl"]):
        p.prog = " ".join(path)
        level = "#" * min(2 + len(path) - 1, 4)
        out += [f"{level} `{' '.join(path)}`", "", "```text", p.format_help().rstrip(), "```", ""]
    return "\n".join(out)


def _fetch(url: str, timeout: float = 10):
    """The release metadata as a dict, MISSING when the channel has none (404), None when it cannot be read."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 - fixed public https URL
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        return MISSING if exc.code == 404 else None
    except Exception:  # noqa: BLE001 - offline or a bad answer: the page says so, the build goes on
        return None


def install_page(fetch: Callable[[str], Optional[dict]] = _fetch) -> str:
    out = ["The newest release of each channel, read from its public release metadata when this site was built.", ""]
    for channel, folder, made_by in CHANNELS:
        meta = fetch(f"{BUCKET}/{folder}/release.json")
        out += [f"**{channel}** ({made_by}):", ""]
        if meta == MISSING:
            out += ["No release of this channel is published yet.", ""]
            continue
        if not isinstance(meta, dict) or not meta.get("version"):
            out += [f"Its release metadata could not be read when this site was built ({BUCKET}/{folder}/release.json).", ""]
            continue
        index = meta.get("index_url", "")
        out += [f"Version **{meta['version']}** (tag `{meta.get('tag', '')}`, commit `{str(meta.get('commit', ''))[:12]}`).",
                "", "```bash",
                f"pip install --index-url {index} \\",
                f"    --extra-index-url {PYPI} \"kaos-lib[zitadel]=={meta['version']}\"",
                "```", ""]
        if meta.get("recommended"):
            out += ["The exact file, as platform images install it:", "", "```bash",
                    f"pip install \"{meta['recommended']}\"", "```", ""]
    return "\n".join(out)


def built_page(version: str, commit: str) -> str:
    return (f"This site documents **kaos-lib {version}**" + (f", built from commit `{commit[:12]}`." if commit else ".")
            + "\n")


def _commit(root: pathlib.Path) -> str:
    sha = os.environ.get("KAOS_LIB_DOCS_COMMIT", "")
    if sha:
        return sha
    try:
        return subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip()
    except Exception:  # noqa: BLE001 - not a git checkout (an sdist)
        return ""


def generate(docs_dir: pathlib.Path, fetch: Callable[[str], Optional[dict]] = _fetch) -> list:
    root = docs_dir.resolve().parent
    sys.path.insert(0, str(root / "src"))
    from kaos_lib import __version__, cli  # the checkout's own code, not whatever is installed

    gen = docs_dir / "generated"
    gen.mkdir(parents=True, exist_ok=True)
    pages = {"cli.md": cli_reference(cli.build_parser()),
             "built.md": built_page(os.environ.get("KAOS_LIB_DOCS_VERSION") or __version__, _commit(root)),
             "install.md": install_page(fetch)}
    for name, text in pages.items():
        target = gen / name
        if not target.exists() or target.read_text() != text:  # unchanged: no rewrite, so `mkdocs serve` does not loop
            target.write_text(text)
    return sorted(pages)


if __name__ == "__main__":
    print("generated:", ", ".join(generate(pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "docs"))))
