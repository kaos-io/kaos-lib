"""Run a step's module with the platform's `/work` folder mapped into a local folder.

Why: the platform runs every step in a container whose `/work/output/<name>.json` is where results go, and many steps
write there with a fixed path. A laptop must not (and usually cannot) create `/work`, so this launcher, started by
`kaosctl step run` with the step's own Python, redirects paths under `/work` to `$KAOS_LOCAL_WORK` and then runs the
step's module as `python -m` would. It uses only the standard library, because it runs inside the step's environment.

Usage: python workmap.py <module> [arguments for the module ...]
"""
import builtins
import io
import os
import pathlib
import runpy
import sys

PREFIX = "/work"
_real = {}


def _map(path):
    """The local path for a path under /work; anything else is returned unchanged."""
    root = os.environ.get("KAOS_LOCAL_WORK")
    if not root or not isinstance(path, (str, os.PathLike)):
        return path
    text = os.fspath(path)
    if not isinstance(text, str):
        return path
    flat = text.replace("\\", "/")
    if flat == PREFIX or flat.startswith(PREFIX + "/"):
        return os.path.join(root, *[p for p in flat[len(PREFIX):].split("/") if p])
    return path


def _wrap(owner, name, positions=(0,)):
    """Replace owner.name by a function that maps the path arguments at `positions`."""
    original = getattr(owner, name)
    _real[(owner.__name__, name)] = original

    def mapped(*args, **kwargs):
        args = list(args)
        for i in positions:
            if i < len(args):
                args[i] = _map(args[i])
        for key in ("path", "src", "dst"):
            if key in kwargs:
                kwargs[key] = _map(kwargs[key])
        return original(*args, **kwargs)
    mapped.__name__ = getattr(original, "__name__", name)
    setattr(owner, name, mapped)


def install():
    """Patch the file functions the standard library and pathlib use to reach a path."""
    for name in ("open", "makedirs", "mkdir", "listdir", "scandir", "stat", "lstat", "remove", "unlink", "rmdir",
                 "chdir", "access", "utime", "chmod", "walk", "readlink", "truncate"):
        if hasattr(os, name):
            _wrap(os, name)
    for name in ("rename", "replace", "link", "symlink"):
        if hasattr(os, name):
            _wrap(os, name, (0, 1))
    _wrap(builtins, "open")
    _wrap(io, "open")
    accessor = getattr(pathlib, "_NormalAccessor", None)   # Python 3.9 and 3.10 bind os functions inside pathlib itself
    for name in ("stat", "lstat", "open", "listdir", "scandir", "chmod", "mkdir", "unlink", "link", "symlink", "rmdir",
                 "rename", "replace", "readlink", "utime"):
        if accessor is not None and name in vars(accessor):
            setattr(accessor, name, staticmethod(getattr(os, name)))


def main(argv):
    if len(argv) < 2:
        sys.exit("usage: workmap.py <module> [args ...]")
    module = argv[1]
    install()
    sys.argv = [module] + argv[2:]
    sys.path.insert(0, os.getcwd())          # `python -m` puts the current folder first; so do we
    runpy.run_module(module, run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    main(sys.argv)
