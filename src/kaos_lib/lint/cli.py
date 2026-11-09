"""The command line of the linter: `kaosctl lint` and the standalone entry the PR gate runs.

Why: one implementation behind both, so the gate and a laptop print the same JSON bytes. It reads local files only:
no login, no network, no client code executed.
"""
from __future__ import annotations

import argparse
import pathlib
import sys
from typing import Optional

from . import render
from .graph import graph_json
from .catalogue import CatalogueError, default_catalogue, empty_catalogue, read_context, read_file
from .constants import PIPELINE_FILE, RULESET_VERSION
from .engine import MissingPipeline, lint_project
from .model import Report
from .schema import schema_json

EXIT_OK, EXIT_USAGE, EXIT_ERRORS = 0, 1, 2   # as kaosctl: 1 = cannot run, 2 = the thing checked is invalid


def add_arguments(sp: argparse.ArgumentParser) -> None:
    """Add the lint options to a parser (`kaosctl lint` and the standalone entry share them)."""
    sp.add_argument("path", nargs="?", default=".", help="your app folder (default: the current folder)")
    sp.add_argument("--pipeline", default=PIPELINE_FILE, help=f"the pipeline file in that folder (default {PIPELINE_FILE})")
    sp.add_argument("--format", choices=("text", "json", "markdown", "status"), default="text",
                    help="text for a terminal (default), json for tools, markdown for a pull request comment, "
                         "status for a one-line summary (a commit status text)")
    sp.add_argument("--output", metavar="FILE", help="write the report to FILE instead of the screen")
    facts = sp.add_mutually_exclusive_group()
    facts.add_argument("--context", metavar="FILE",
                       help="your project's platform context (pipeline-context.yaml): the compute classes and HPC "
                            "(Slurm) limits of your project. Without it the built-in defaults apply and the checks "
                            "that need your classes are skipped")
    facts.add_argument("--catalogue", metavar="FILE",
                       help="a catalogue file written by --export-catalogue, or none to skip every check that "
                            "needs one")
    sp.add_argument("--export-catalogue", metavar="FILE",
                    help="write the catalogue read from --context to FILE and stop (no linting)")
    sp.add_argument("--from-report", metavar="FILE",
                    help="render a JSON report you saved earlier instead of linting (text or markdown output)")
    sp.add_argument("--schema", action="store_true",
                    help="print what step() accepts (names, types, allowed values, docs, links) as JSON, versioned "
                         "with the rule set, and stop: editors read it for completion and hover text")
    sp.add_argument("--graph", action="store_true",
                    help="print the pipeline's steps and their dependencies as JSON, read from the file without "
                         "running it, and stop: editors draw it")
    sp.add_argument("--expect-ruleset", metavar="VERSION",
                    help="refuse to run unless the rule set is exactly this version")
    sp.add_argument("--file-link-base", metavar="URL", help="markdown output: link each file:line under this URL")


def _catalogue(args):
    if args.context:
        return read_context(args.context)
    if args.catalogue == "none":
        return empty_catalogue()
    if args.catalogue:
        return read_file(args.catalogue)
    return default_catalogue()


def _emit(args, body: str) -> None:
    if args.output:
        pathlib.Path(args.output).write_text(body, encoding="utf-8")
    else:
        sys.stdout.write(body)


def run(args) -> int:
    """Run the linter for parsed arguments. Exit 0: no errors; 2: errors found; 1: it could not run."""
    if args.expect_ruleset and args.expect_ruleset != RULESET_VERSION:
        print(f"ERROR: this kaos-lib has rule set {RULESET_VERSION}, not {args.expect_ruleset}. Reports of "
              f"different rule sets are never mixed: install the matching kaos-lib.", file=sys.stderr)
        return EXIT_USAGE
    try:
        if args.schema:
            _emit(args, schema_json())
            return EXIT_OK
        if args.graph:
            _emit(args, graph_json(args.path, args.pipeline))
            return EXIT_OK
        if args.export_catalogue:
            pathlib.Path(args.export_catalogue).write_text(_catalogue(args).to_json(), encoding="utf-8")
            return EXIT_OK
        if args.from_report:
            report = Report.from_json(pathlib.Path(args.from_report).read_text(encoding="utf-8"))
            if report.ruleset_version != RULESET_VERSION and args.expect_ruleset:
                print("ERROR: the report was made by another rule set.", file=sys.stderr)
                return EXIT_USAGE
        else:
            report = lint_project(args.path, _catalogue(args), args.pipeline)
    except (CatalogueError, MissingPipeline, OSError, ValueError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_USAGE
    _emit(args, {"json": report.to_json, "markdown": lambda: render.markdown(report, args.file_link_base),
                 "text": lambda: render.text(report),
                 "status": lambda: render.status_description(report) + "\n"}[args.format]())
    return EXIT_ERRORS if report.errors else EXIT_OK


def main(argv: Optional[list] = None) -> int:
    """The standalone entry: `python standalone.py [options] [path]`."""
    parser = argparse.ArgumentParser(prog="kaosctl lint", description="Check a pipeline.py without running it.")
    add_arguments(parser)
    return run(parser.parse_args(argv))
