"""One wheel and one site run on every platform: no address of any platform is built into either.

PRD novelcore/kaos#2017 F-55. The addresses come from `kaos_lib.addresses` (environment, context file, what the
platform published); with none, the answer is "none" and the command says so. The guard at the end fails when the
dev project's name is in the package source, the built wheel or the built docs site.
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import zipfile

import pytest

from kaos_lib import addresses, channel, cli
from kaos_lib.lint import registry
from kaos_lib.lint.schema import build_schema
from kaos_lib.studio import kaoslib
from kaos_lib.errors import KaosLibError

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEV = "kaos-dev-511509"
BLOCK = {"releases_base": "https://bucket.example.test/", "index_url": "https://index.example.test/simple/",
         "docs_base": "https://bucket.example.test/docs/v1/", "docs_current": "https://bucket.example.test/docs/current/"}


@pytest.fixture(autouse=True)
def no_env(monkeypatch):
    for name in (*addresses.ENV.values(), addresses.LINT_ENV):
        monkeypatch.delenv(name, raising=False)


def context(tmp_path, block=BLOCK):
    path = tmp_path / "ctx.yaml"
    path.write_text("kaosLib:\n  spec: ''\n  support:\n    addresses:\n" +
                    "".join(f"      {k}: {v}\n" for k, v in block.items()))
    return str(path)


# ------------------------------------------------------------------ the resolver
def test_no_compiled_address():
    assert channel.RELEASES_BASE is None and channel.INDEXES is None
    from kaos_lib.lint import constants
    assert constants.DOC_BASE is None


def test_nothing_known_gives_none():
    found = addresses.resolve()
    assert (found.releases_base, found.index_url, found.docs_base, found.docs_current) == (None,) * 4


def test_the_order_is_environment_then_context_then_platform(tmp_path, monkeypatch):
    addresses.save_platform("https://lakefs.example.test", {"addresses": {
        "releases_base": "https://platform.example.test", "index_url": "https://platform.example.test/simple/",
        "docs_base": "https://platform.example.test/docs/v9/", "docs_current": "https://platform.example.test/docs/current/"}})
    assert addresses.resolve().releases_base == "https://platform.example.test"
    ctx = context(tmp_path)
    found = addresses.resolve(ctx)
    assert found.releases_base == "https://bucket.example.test"              # no trailing slash
    assert found.docs_current == BLOCK["docs_current"] and "context file" in found.describe("releases_base")
    monkeypatch.setenv("KAOS_LIB_RELEASES_BASE", "https://env.example.test/")
    monkeypatch.setenv("KAOS_LIB_INDEX_URL", "https://env.example.test/simple/")
    monkeypatch.setenv("KAOS_LIB_DOCS_BASE", "https://env.example.test/docs/v2/")
    found = addresses.resolve(ctx)
    assert (found.releases_base, found.index_url, found.docs_base) == (
        "https://env.example.test", "https://env.example.test/simple/", "https://env.example.test/docs/v2/")
    assert found.docs_current == BLOCK["docs_current"]                      # not in the environment: the next source


def test_a_published_address_that_is_not_https_is_ignored(tmp_path):
    ctx = context(tmp_path, {"releases_base": "http://bucket.example.test", "index_url": "file:///x"})
    found = addresses.resolve(ctx)
    assert found.releases_base is None and found.index_url is None


def test_the_platform_entry_is_replaced_and_removed():
    addresses.save_platform("https://p.example.test", {"addresses": BLOCK, "recommended": "==1.0.0"})
    assert addresses.cached_recommended() == "==1.0.0"
    addresses.save_platform("https://p.example.test", {"version": "1"})
    assert addresses.cached_recommended() is None and addresses.resolve().releases_base is None


# ------------------------------------------------------------------ upgrade and vscode install
def run(capsys, *argv):
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_upgrade_with_neither_recommendation_nor_address_fails_with_the_cause(capsys, monkeypatch):
    monkeypatch.delenv("KAOS_LIB_RELEASES_BASE", raising=False)
    monkeypatch.setattr(cli.subprocess, "call", lambda cmd: pytest.fail("installed something"))
    code, _, err = run(capsys, "upgrade")
    assert code == 1 and "knows no release address" in err and DEV not in err


def test_vscode_install_without_an_address_says_so(capsys, monkeypatch):
    monkeypatch.delenv("KAOS_LIB_RELEASES_BASE", raising=False)
    code, _, err = run(capsys, "vscode", "install", "--dry-run")
    assert code == 1 and "knows no release address" in err and DEV not in err


# ------------------------------------------------------------------ the kaos-lib a laptop installs
def test_the_platform_recommendation_comes_after_the_context_and_before_the_dockerfile(tmp_path, monkeypatch):
    monkeypatch.setenv("KAOS_LIB_INDEX_URL", BLOCK["index_url"])
    addresses.save_platform("https://p.example.test", {"recommended": "==2.0.0rc1"})
    ctx = tmp_path / "c.yaml"
    ctx.write_text("kaosLib:\n  spec: 'kaos-lib[zitadel]==3.0.0'\n")
    assert kaoslib.resolve(None, str(ctx), "kaos-lib==1.0.0").requirement.endswith("==3.0.0")
    chosen = kaoslib.resolve(None, None, "kaos-lib==1.0.0")
    assert chosen.requirement.endswith("==2.0.0rc1") and "platform recommends" in chosen.source
    assert chosen.index_urls == [BLOCK["index_url"]]
    addresses.save_platform("https://p.example.test", {})
    assert kaoslib.resolve(None, None, "kaos-lib==1.0.0").requirement.endswith("==1.0.0")


def test_the_own_version_needs_the_platforms_index():
    with pytest.raises(KaosLibError, match="no package index") as err:
        kaoslib.resolve(None, None, None)
    assert DEV not in str(err.value)


def test_the_own_version_is_installed_from_the_platforms_index(monkeypatch):
    monkeypatch.setenv("KAOS_LIB_INDEX_URL", BLOCK["index_url"])
    spec = kaoslib.resolve(None, None, None)
    assert spec.index_urls == [BLOCK["index_url"]] and "own version" in spec.source


# ------------------------------------------------------------------ lint links
def test_lint_names_no_link_without_a_doc_base(capsys, tmp_path):
    registry.set_doc_base(None)
    schema = build_schema()
    assert schema["guide"] == "" and all(r["doc"] == "" for r in schema["rules"])
    assert all(p["links"] == [] for p in schema["step"]["parameters"])
    from lint_corpus import repo, write_repo
    root = write_repo(tmp_path, repo('    step("a")\n'))
    assert cli.main(["lint", str(root), "--format", "markdown"]) == 2
    out = capsys.readouterr().out
    assert "[Details]" not in out and "](" not in out.split("| rule |", 1)[1].split("\n", 3)[3] and "http" not in out
    assert cli.main(["lint", str(root)]) == 2
    assert "docs:" not in capsys.readouterr().out


def test_lint_doc_base_flag_and_environment(capsys, tmp_path, monkeypatch):
    from lint_corpus import repo, write_repo
    root = write_repo(tmp_path, repo('    step("a")\n'))
    assert cli.main(["lint", str(root), "--format", "json", "--doc-base", "https://x.example.test/v/lint"]) == 2
    docs = {f["doc"] for f in json.loads(capsys.readouterr().out)["findings"]}
    assert docs and all(d.startswith("https://x.example.test/v/lint/L-") and d.endswith(".html") for d in docs)
    monkeypatch.setenv("KAOS_LIB_LINT_DOC_BASE", "https://e.example.test/lint/")
    cli.main(["lint", str(root), "--format", "json"])
    assert all(f["doc"].startswith("https://e.example.test/lint/L-") for f in json.loads(capsys.readouterr().out)["findings"])
    monkeypatch.delenv("KAOS_LIB_LINT_DOC_BASE")
    monkeypatch.setenv("KAOS_LIB_DOCS_BASE", "https://d.example.test/docs/v1/")
    cli.main(["lint", str(root), "--format", "json"])
    assert all(f["doc"].startswith("https://d.example.test/docs/v1/lint/L-") for f in json.loads(capsys.readouterr().out)["findings"])
    assert cli.main(["lint", str(root), "--doc-base", "http://insecure.example.test/"]) == 1


# ------------------------------------------------------------------ the guard
def _unavailable(reason: str):
    """A guard that cannot run is a failure in CI ($CI or $KAOS_LIB_CI set) and a skip on a laptop."""
    if os.environ.get("CI") or os.environ.get("KAOS_LIB_CI"):
        pytest.fail(f"{reason}: install the test extra (pip install -e '.[test]') so this guard runs in CI")
    pytest.skip(reason)


def _hits(root: pathlib.Path) -> list:
    needle = DEV.encode()
    return [str(p.relative_to(root)) for p in sorted(root.rglob("*"))
            if p.is_file() and "__pycache__" not in p.parts and not any(x.endswith(".egg-info") for x in p.parts)
            and needle in p.read_bytes()]


def test_the_package_source_names_no_dev_project():
    assert _hits(ROOT / "src") == []


def _build(tmp_path, *command):
    return subprocess.run([sys.executable, "-m", *command], cwd=ROOT, capture_output=True, text=True)


def test_the_built_wheel_names_no_dev_project(tmp_path):
    try:
        import build  # noqa: F401
    except ImportError:
        _unavailable("the `build` package is not installed")
    out = tmp_path / "dist"
    work = tmp_path / "src-copy"
    shutil.copytree(ROOT, work, ignore=shutil.ignore_patterns(".git", "node_modules", "__pycache__", "*.egg-info", "build", "dist", "site"))
    done = subprocess.run([sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", str(out)],
                          cwd=work, capture_output=True, text=True)
    if done.returncode:
        _unavailable(f"the wheel could not be built here: {done.stderr[-300:]}")
    wheel = next(out.glob("*.whl"))
    with zipfile.ZipFile(wheel) as z:
        bad = [n for n in z.namelist() if DEV.encode() in z.read(n)]
    assert bad == [], bad


def test_the_built_docs_site_names_no_dev_project(tmp_path, monkeypatch):
    try:
        import mkdocs  # noqa: F401
    except ImportError:
        _unavailable("mkdocs is not installed")
    site = tmp_path / "site"
    env = {k: v for k, v in os.environ.items() if not k.startswith("KAOS_LIB_")}
    env.update(DOCS_CHECK_OFFLINE="1", SOURCE_DATE_EPOCH="1700000000")
    done = subprocess.run([sys.executable, "-m", "mkdocs", "build", "--strict", "-q", "-d", str(site)],
                          cwd=ROOT, capture_output=True, text=True, env=env)
    if done.returncode and "No module named" in done.stderr:
        _unavailable("the docs dependencies are not installed")
    assert done.returncode == 0, done.stderr[-800:] + done.stdout[-800:]
    assert _hits(site) == []
    assert "<loc>" not in (site / "sitemap.xml").read_text(), "no site_url, so no sitemap that names a host"
    assert 'rel="canonical"' not in (site / "index.html").read_text()
