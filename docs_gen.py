"""Generate the pages of the documentation site that must never drift from the code or the releases.

Run by the mkdocs hook `docs/hooks.py` on every build (so `mkdocs build` alone keeps them current), or by hand:
`python docs_gen.py docs`. It writes, under `<docs>/generated/`:

- `cli.md`: every `kaosctl` command's `--help`, taken from the argparse parser itself (`kaos_lib.cli.build_parser`);
- `built.md`: the kaos-lib version and commit this site was built from;
- `install.md`: how to get kaosctl from your platform. It names no package index, no bucket and no release: a site
  built once is read on every platform, so the page points at `kaosctl upgrade` and the console.

Nothing here reads the network or the clock, so the same commit builds the same pages (with `SOURCE_DATE_EPOCH`).
"""
from __future__ import annotations

import argparse
import os
import pathlib
import subprocess
import sys
from typing import Callable, Optional



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
           "it documents.", ""]
    for path, p in _walk(parser, ["kaosctl"]):
        p.prog = " ".join(path)
        level = "#" * min(2 + len(path) - 1, 4)
        out += [f"{level} `{' '.join(path)}`", "", "```text", p.format_help().rstrip(), "```", ""]
    return "\n".join(out)


def install_page(fetch: Optional[Callable] = None) -> str:
    """How to install kaosctl, the same on every platform: no address, no release read at build time.
    (``fetch`` is accepted and ignored: older callers passed one.)"""
    return "\n".join([
        "Your platform publishes the kaos-lib it supports, and `kaosctl` finds it for you.", "",
        "- If you have `kaosctl`, run `kaosctl login` in your app folder, then `kaosctl upgrade`. It installs the "
        "version your platform recommends. Run `kaosctl --version` to see what you have and what the platform "
        "recommends.",
        "- If you do not have it yet, open the console of your platform: its **Pipelines** page shows the line "
        "that installs `kaosctl`. Copy it into a terminal.",
        "- To add the editor extension for VS Code afterwards, run `kaosctl vscode install`.", ""])


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


def generate(docs_dir: pathlib.Path, fetch: Optional[Callable] = None) -> list:
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
