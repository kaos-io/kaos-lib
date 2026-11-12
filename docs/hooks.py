"""mkdocs hook: regenerate the pages that must never drift (docs_gen.py), and run every example of the guide
(docs_examples.py) before every build: an example that no longer lints or runs stops the build."""
import importlib.util
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, _ROOT / file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def on_pre_build(config, **kwargs):
    from mkdocs.exceptions import PluginError
    _load("kaos_lib_docs_gen", "docs_gen.py").generate(pathlib.Path(config["docs_dir"]))
    sys.path.insert(0, str(_ROOT / "src"))
    try:
        _load("docs_examples", "docs_examples.py").check_all()
    except Exception as exc:  # noqa: BLE001 - whatever is wrong with an example stops the build
        raise PluginError(f"docs examples: {type(exc).__name__}: {exc}") from None
    finally:
        sys.path.remove(str(_ROOT / "src"))
