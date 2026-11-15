"""The site's generated pages: the CLI reference never drifts from the parser, and the install page names no
platform and reads nothing at build time."""
import importlib.util
import pathlib

from kaos_lib import cli

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("docs_gen", ROOT / "docs_gen.py")
docs_gen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(docs_gen)

def _commands(parser, path):
    yield " ".join(path)
    sub = docs_gen._subparsers(parser)
    if sub:
        for name, child in sub.choices.items():
            yield from _commands(child, path + [name])


def test_every_command_of_the_parser_has_its_help_in_the_reference():
    page = docs_gen.cli_reference(cli.build_parser())
    for command in _commands(cli.build_parser(), ["kaosctl"]):
        assert f"`{command}`" in page, command
    assert "kaosctl dataset create" in page and "--layout" in page
    assert "kaos-cli" not in page and "kubecore" not in page.replace("kubecore/", "")


def test_the_install_page_names_no_index_no_bucket_and_no_release():
    page = docs_gen.install_page()
    assert "kaosctl upgrade" in page and "package index" in page and "console" in page
    for word in ("http://", "https://", "--index-url", "release.json", "pip install"):
        assert word not in page, word
    assert page == docs_gen.install_page(lambda url: {"version": "9"}), "it reads nothing: the same page every build"


def test_generate_writes_the_pages_and_leaves_unchanged_ones_alone(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    names = docs_gen.generate(docs)
    assert names == ["built.md", "cli.md", "install.md"]
    built = docs / "generated" / "built.md"
    assert "This site documents **kaos-lib" in built.read_text()
    mtime = built.stat().st_mtime_ns
    docs_gen.generate(docs)
    assert built.stat().st_mtime_ns == mtime                                 # no rewrite: `mkdocs serve` does not loop
