"""The site's generated pages: the CLI reference never drifts from the parser, and the install page says exactly
what each channel has published (or that it could not be read) without ever failing the build."""
import importlib.util
import pathlib

from kaos_lib import cli

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("docs_gen", ROOT / "docs_gen.py")
docs_gen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(docs_gen)

RC = {"version": "0.4.0rc5", "tag": "v0.4.0-rc.5", "commit": "105e7918cb74abcdef",
      "index_url": "https://example.invalid/kaos-lib-rc/simple/",
      "recommended": "kaos-lib[zitadel] @ https://example.invalid/kaos_lib-0.4.0rc5-py3-none-any.whl#sha256=ab"}


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


def test_a_published_channel_shows_its_version_and_both_install_forms():
    page = docs_gen.install_page(lambda url: RC if "/rc/" in url else docs_gen.MISSING)
    assert '"kaos-lib[zitadel]==0.4.0rc5"' in page and "--index-url https://example.invalid/kaos-lib-rc/simple/" in page
    assert RC["recommended"] in page and "v0.4.0-rc.5" in page and "105e7918cb74" in page
    assert "No release of this channel is published yet." in page          # stable: 404


def test_unreadable_metadata_is_said_and_never_called_unpublished():
    page = docs_gen.install_page(lambda url: None)
    assert page.count("could not be read") == 2 and "published yet" not in page


def test_generate_writes_the_pages_and_leaves_unchanged_ones_alone(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    names = docs_gen.generate(docs, fetch=lambda url: docs_gen.MISSING)
    assert names == ["built.md", "cli.md", "install.md"]
    built = docs / "generated" / "built.md"
    assert "This site documents **kaos-lib" in built.read_text()
    mtime = built.stat().st_mtime_ns
    docs_gen.generate(docs, fetch=lambda url: docs_gen.MISSING)
    assert built.stat().st_mtime_ns == mtime                                 # no rewrite: `mkdocs serve` does not loop
