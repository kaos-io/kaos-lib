"""Run the linter without importing the rest of kaos-lib: `python3 -I standalone.py [options] [path]`.

Why: the PR gate runs in an image that has Python and PyYAML but not the packages the rest of kaos-lib imports at
start-up (requests, packaging). The linter itself needs only the standard library and PyYAML, so this script gives
`kaos_lib` an empty package object that points at the unpacked wheel and imports `kaos_lib.lint` from it. The
gate unpacks the pinned wheel and runs this file; a laptop runs `kaosctl lint`, which reaches the same `main`.
Run it with -I so neither the current folder (the client's repository) nor the environment decides what is imported.
"""
import os
import sys
import types


def _load_main():
    package_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # .../kaos_lib
    stub = types.ModuleType("kaos_lib")
    stub.__path__ = [package_dir]   # makes `kaos_lib.lint` importable without running kaos_lib/__init__.py
    sys.modules["kaos_lib"] = stub
    from kaos_lib.lint.cli import main
    return main


if __name__ == "__main__":
    sys.exit(_load_main()(sys.argv[1:]))
