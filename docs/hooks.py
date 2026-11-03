"""mkdocs hook: regenerate the pages that must never drift (docs_gen.py) before every build."""
import importlib.util
import pathlib

_GEN = pathlib.Path(__file__).resolve().parent.parent / "docs_gen.py"


def on_pre_build(config, **kwargs):
    spec = importlib.util.spec_from_file_location("kaos_lib_docs_gen", _GEN)
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    gen.generate(pathlib.Path(config["docs_dir"]))
