#!/usr/bin/env python3
"""Three checks of the client documentation: words, removed names, links.

kaos-lib and the two pipeline templates (novelcore/hera-pipeline-template, novelcore/yolo-pipelines-template)
form one guide and link to each other. This file is the only copy of the checks. It lives in kaos-lib and
checks any of the three repositories:

    python3 docs_check.py              this checkout (kaos-lib); also a mkdocs hook, so `mkdocs build` runs it
    python3 docs_check.py <folder>     a checkout of a template (its scripts/check-docs.sh and the platform's
                                       docs build of the templates do this)
    python3 docs_check.py --self-test  the checker's own cases

  words          client pages never name what the platform is built from
  removed names  nothing describes a step or a folder that no longer exists
  links          every link of the repository resolves, in it and in the other two, and every link of the
                 other two into it resolves

The other two repositories are read at their trunk: downloaded, or from a checkout named by DOCS_CHECK_KAOS_LIB,
DOCS_CHECK_HERA or DOCS_CHECK_YOLO (kaos-lib is this checkout unless named). A download that fails is an
error: nothing is skipped silently. DOCS_CHECK_OFFLINE=1 checks the repository alone and prints what it skipped.
DOCS_CHECK_EXTERNAL=1 also fetches every other http(s) link.
"""
from __future__ import annotations

import atexit
import io
import os
import pathlib
import re
import shutil
import sys
import tarfile
import tempfile
import time
import unicodedata
import urllib.error
import urllib.request

BUCKET = "https://storage.googleapis.com/kaos-dev-511509-kaos-lib/"
REPOS = {
    "KAOS_LIB": {
        "repo": "kaos-io/kaos-lib", "trunk": "main",
        "sites": (BUCKET + "docs/",),
        "generated": ("docs/generated/cli.md",),             # written by the build (docs_gen.py), not committed
        # Not client pages: the changelog records history, removed names included; docs/design/ is for the platform team.
        "not_client": ("CHANGELOG.md", "docs/design/"),
    },
    "HERA": {
        "repo": "novelcore/hera-pipeline-template", "trunk": "dev",
        "sites": ("https://novelcore.github.io/hera-pipeline-template/", BUCKET + "template-docs/hera-pipeline-template/"),
        "generated": (), "not_client": (),
    },
    "YOLO": {
        "repo": "novelcore/yolo-pipelines-template", "trunk": "dev",
        "sites": ("https://novelcore.github.io/yolo-pipelines-template/", BUCKET + "template-docs/yolo-pipelines-template/"),
        "generated": (), "not_client": (),
    },
}

# (pattern, what it is, what to write instead). Matched without case, on the text a reader sees (not on link targets).
WORDS = (
    (r"\bargo(?:cd|proj[\w.-]*|_\w+)?\b", "the workflow engine's name",
     'write "the run page", "the run form" or "the platform"'),
    (r"\bkubectl\b", "a cluster command", "clients have no cluster access: name the console page or the kaosctl command"),
    (r"\bnamespaces?\b", "a cluster word", 'write "project"'),
    (r"\bcrossplane\b", "a platform component", 'write "the platform"'),
    (r"\bkubecore-(?:dev|prod)-kaos[\w-]*|\bkaos-v3\b|\bgke-(?:dev|prod)\b|\bprd240-kaos\b", "a cluster name",
     'write "the platform" or "your project\'s machines"'),
)
VENDORED = "an app holds no kubecore/ folder: the platform runs its own pipeline engine"
# (pattern, why, what is allowed: a pattern the match itself may fit)
REMOVED = (
    (r"\bdataset[-_]loading\b", "the dataset-loading step was removed: the platform pins the run's dataset", None),
    (r"\bdata[-_]summary\b", "the data-summary step was removed from the templates", None),
    (r"\bcompose[-_]and[-_]validate\b", "the compose-and-validate step was removed: the platform composes the parameters", None),
    # Any path through a kubecore/ folder. Allowed: the import shim of kaos-lib itself (src/kubecore/), the app's
    # settings folder (.kubecore/) and the dataset cache (.cache/kubecore/).
    (r"[\w.~<>/-]*kubecore/", VENDORED, r"(?:^|/)src/kubecore/$|(?:^|/)\.kubecore/$|\.cache/kubecore/$"),
    (r"\bkubecore`?\s+(?:folder|directory)\b", VENDORED, None),
    (r"\bKUBECORE_STAGED_DIR\b", "the staged-copy variable is KAOS_STAGED_ROOT: one folder for each input under it", None),
)

SKIP_DIRS = {"node_modules", "site", "venv", "build", "dist", "out", "__pycache__", "generated"}
FENCE = re.compile(r"^(```|~~~).*?^\1[^\n]*$", re.S | re.M)
INLINE_CODE = re.compile(r"`[^`\n]*`")
LINKS = (
    re.compile(r"!?\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)"),                 # [text](target), ![alt](image)
    re.compile(r"\[!\[[^\]]*\]\([^)]*\)\]\(\s*<?([^)\s>]+)"),                              # [![alt](image)](target)
    re.compile(r"^\s*\[[^\]]+\]:\s+(\S+)", re.M),                                          # [name]: target
    re.compile(r"<(?:a|img)\b[^>]*?\b(?:href|src)\s*=\s*[\"']([^\"']+)[\"']", re.I),          # <a href>, <img src>
)
LINE_ANCHOR = re.compile(r"L\d+(?:-L\d+)?$")                # a line of a file on GitHub, not a heading
URL = re.compile(r"https?://[^\s)>\]\"'`|]+")
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$", re.M)
_fetched: dict = {}

HERE = pathlib.Path(__file__).resolve().parent              # the kaos-lib checkout this file is in


def find_root(start: pathlib.Path) -> pathlib.Path:
    for folder in (start, *start.parents):
        if (folder / "mkdocs.yml").is_file():
            return folder
    raise SystemExit(f"docs check: no mkdocs.yml in {start} or above it")


def key_of(root: pathlib.Path) -> str:
    """Which of the three repositories `root` is, from `repo_name` in its mkdocs.yml."""
    m = re.search(r"^repo_name:\s*(\S+)", (root / "mkdocs.yml").read_text(encoding="utf-8"), re.M)
    for key, spec in REPOS.items():
        if m and m.group(1) == spec["repo"]:
            return key
    raise SystemExit(f"docs check: {root / 'mkdocs.yml'} names none of the three repositories in repo_name")


def pages(root: pathlib.Path) -> list:
    """Every Markdown file of the repository, without hidden folders, environments and build output."""
    found = []
    for folder, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in SKIP_DIRS)
        found += [pathlib.Path(folder, n) for n in sorted(names) if n.endswith(".md")]
    return found


def listed(rel: str, entries) -> bool:
    return any(rel == e or (e.endswith("/") and rel.startswith(e)) for e in entries)


def visible(line: str) -> str:
    """The line as a reader sees it: without link targets and bare addresses, with link titles."""
    line = re.sub(r"\]\(\s*[^)\s]*(?:\s+\"([^\"]*)\")?\s*\)", lambda m: "] " + (m.group(1) or ""), line)
    return URL.sub("", line)


# ------------------------------------------------------------------ words and removed names
def check_text(root: pathlib.Path, key: str) -> tuple:
    spec = REPOS[key]
    words, removed = [], []
    code = sorted(p for p in (root / "docs" / "examples").rglob("*") if p.suffix in (".py", ".yaml"))   # shown on pages
    for path in [*pages(root), root / "mkdocs.yml", *code]:
        rel = path.relative_to(root).as_posix()
        if listed(rel, spec["not_client"]):
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            seen = visible(line)
            for pattern, what, instead in WORDS:
                for m in re.finditer(pattern, seen, re.I):
                    words.append(f"{rel}:{number}: \"{m.group(0)}\" is {what}; {instead}")
            for pattern, why, allowed in REMOVED:
                for m in re.finditer(pattern, line, re.I):
                    if not (allowed and re.search(allowed, m.group(0))):
                        removed.append(f"{rel}:{number}: \"{m.group(0)}\": {why}")
    return words, removed


# ------------------------------------------------------------------ links
def slug(heading: str) -> str:
    """The anchor mkdocs gives a heading (Python-Markdown's toc slugify)."""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", heading)
    text = re.sub(r"<[^>]+>|[`*]", "", text)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[-\s]+", "-", re.sub(r"[^\w\s-]", "", text).strip().lower())


def anchors(path: pathlib.Path) -> set:
    text = FENCE.sub("", path.read_text(encoding="utf-8"))
    out, count = set(re.findall(r"<a\s+(?:id|name)=\"([^\"]+)\"", text)), {}
    for m in HEADING.finditer(text):
        heading = m.group(1)
        explicit = re.search(r"\{:?\s*#([\w-]+)[^}]*\}\s*$", heading)
        base = explicit.group(1) if explicit else slug(heading)
        count[base] = count.get(base, 0) + 1
        out.add(base if count[base] == 1 else f"{base}_{count[base] - 1}")
    return out


def in_repo(url: str):
    """(repository key, path in the repository) for an address of one of the three repositories, else None."""
    url = url.split("#")[0].split("?")[0]
    for key, spec in REPOS.items():
        m = re.match(rf"https://github\.com/{re.escape(spec['repo'])}/(?:blob|tree)/[^/]+/(.+)", url)
        if m:
            return key, m.group(1).rstrip("/")
        for site in spec["sites"]:
            if url.startswith(site):
                page = url[len(site):]
                if page in ("", "index.html"):
                    return key, "docs/index.md"
                if page.endswith(".html"):
                    return key, f"docs/{page[:-5]}.md"
                if page.endswith("/"):
                    return key, f"docs/{page[:-1]}.md"
                return key, f"docs/{page}"
    return None


def missing(tree: pathlib.Path, key: str, rel: str, fragment: str) -> str:
    """Why `rel#fragment` does not resolve in the checkout `tree` of repository `key`; empty when it does."""
    if rel in REPOS[key]["generated"]:
        return ""
    target = tree / rel
    if not target.exists() and rel.startswith("docs/") and rel.endswith(".md"):
        target = tree / rel[:-3] / "index.md"            # a folder address: <page>/ is <page>/index.md
    if not target.exists():
        return "no such file"
    if fragment and target.suffix == ".md" and fragment not in anchors(target):
        return f"no heading with the anchor #{fragment}"
    return ""


def heading_of(url: str) -> str:
    """The heading an address names, if any: `#L3` and `#L3-L9` on a GitHub file page name lines."""
    fragment = url.partition("#")[2]
    return "" if url.startswith("https://github.com/") and LINE_ANCHOR.match(fragment) else fragment


def links(path: pathlib.Path) -> list:
    """(line number, target) of every link of a file: Markdown links outside code, and addresses anywhere."""
    text = path.read_text(encoding="utf-8")
    blank = lambda m: re.sub(r"[^\n]", " ", m.group(0))      # keep the line numbers
    prose = INLINE_CODE.sub(blank, FENCE.sub(blank, text)) if path.suffix == ".md" else ""
    found = {(prose.count("\n", 0, m.start()) + 1, m.group(1)) for pattern in LINKS for m in pattern.finditer(prose)}
    found |= {(text.count("\n", 0, m.start()) + 1, m.group(0).rstrip(".,;:")) for m in URL.finditer(text)}
    return sorted(found)


def fetch(key: str) -> pathlib.Path:
    """The trunk of another repository, downloaded once (the three repositories are public)."""
    if key not in _fetched:
        spec = REPOS[key]
        url = f"https://codeload.github.com/{spec['repo']}/tar.gz/refs/heads/{spec['trunk']}"
        last = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "docs-check"}), timeout=60) as r:
                    raw = r.read()
                break
            except Exception as exc:  # noqa: BLE001 - any network failure is reported the same way
                last = exc
                time.sleep(3 * (attempt + 1))
        else:
            raise SystemExit(f"docs check: cannot download {spec['repo']}@{spec['trunk']} ({last}). Set DOCS_CHECK_{key} "
                             f"to a checkout of it, or DOCS_CHECK_OFFLINE=1 to check this repository alone.")
        dest = pathlib.Path(tempfile.mkdtemp(prefix="docs-check-"))
        atexit.register(shutil.rmtree, dest, True)
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
            tar.extractall(dest, filter="data") if hasattr(tarfile, "data_filter") else tar.extractall(dest)
        _fetched[key] = next(p for p in dest.iterdir() if p.is_dir())
    return _fetched[key]


def answers(url: str) -> bool:
    for attempt in range(3):
        for method in ("HEAD", "GET"):
            try:
                req = urllib.request.Request(url, method=method, headers={"User-Agent": "docs-check"})
                with urllib.request.urlopen(req, timeout=20) as r:
                    return r.status < 400
            except urllib.error.HTTPError as exc:
                if exc.code == 429:
                    time.sleep(3 * (attempt + 1))
                    break
                if method == "GET":
                    return False
            except Exception:  # noqa: BLE001
                if method == "GET":
                    return False
    return True     # still rate-limited: unknown, not broken


def check_links(root: pathlib.Path, key: str, env) -> tuple:
    """(broken links, what was checked, what was skipped) for the repository `key` at `root`."""
    offline = env.get("DOCS_CHECK_OFFLINE") == "1"
    trees = {key: root}
    for other in REPOS:
        if other != key and not offline:
            given = env.get(f"DOCS_CHECK_{other}")
            if given:
                trees[other] = pathlib.Path(given).resolve()
            elif other == "KAOS_LIB" and (HERE / "mkdocs.yml").is_file():
                trees[other] = HERE
            else:
                trees[other] = fetch(other)
            if not (trees[other] / "mkdocs.yml").is_file():
                raise SystemExit(f"docs check: DOCS_CHECK_{other}={given} is not a checkout of {REPOS[other]['repo']}")
    bad, external, unchecked = [], {}, 0
    for path in [*pages(root), root / "mkdocs.yml"]:
        rel = path.relative_to(root).as_posix()
        for number, target in links(path):
            where = f"{rel}:{number}"
            if target.startswith(("mailto:", "tel:")):
                continue
            if target.startswith(("http://", "https://")):
                hit = in_repo(target)
                if hit is None:
                    external.setdefault(target.split("#")[0], where)
                elif hit[0] not in trees:
                    unchecked += 1
                else:
                    why = missing(trees[hit[0]], hit[0], hit[1], heading_of(target))
                    if why:
                        bad.append(f"{where}: {target}: {why} in {REPOS[hit[0]]['repo']} ({hit[1]})")
                continue
            file, _, fragment = target.partition("#")
            dest = path if not file else (path.parent / file.split("?")[0])
            dest_rel = os.path.relpath(dest, root).replace(os.sep, "/")
            why = missing(root, key, dest_rel, fragment) if not dest_rel.startswith("..") else "points outside the repository"
            if why:
                bad.append(f"{where}: {target}: {why}")
    for other, tree in trees.items():                         # what the other two say about this repository
        if other == key:
            continue
        for path in [*pages(tree), tree / "mkdocs.yml"]:
            for number, target in links(path):
                hit = in_repo(target) if target.startswith("https://") else None
                if hit and hit[0] == key:
                    why = missing(root, key, hit[1], heading_of(target))
                    if why:
                        bad.append(f"{REPOS[other]['repo']}@{REPOS[other]['trunk']} {path.relative_to(tree).as_posix()}:{number} "
                                   f"links to {target}: {why} here ({hit[1]})")
    if env.get("DOCS_CHECK_EXTERNAL") == "1":
        bad += [f"{where}: {url}: does not answer" for url, where in sorted(external.items()) if not answers(url)]
    note = f"{len(external)} other addresses" + ("" if env.get("DOCS_CHECK_EXTERNAL") == "1" else " not fetched")
    if len(trees) > 1:
        note += "; with " + ", ".join(f"{REPOS[o]['repo']} at {t}" for o, t in trees.items() if o != key)
    skipped = (f"SKIPPED (DOCS_CHECK_OFFLINE=1): {unchecked} links of this repository into the other two, and every "
               f"link of the other two into this one, were NOT checked") if offline else ""
    return bad, note, skipped


# ------------------------------------------------------------------ entry points
def run(root: pathlib.Path, env=os.environ) -> tuple:
    """(report text, number of findings) of the three checks on the repository at `root`."""
    key = key_of(root)
    words, removed = check_text(root, key)
    broken, note, skipped = check_links(root, key, env)
    out = [f"docs check of {REPOS[key]['repo']} ({root})"]
    for title, found, hint in (
            ("words", words, "client pages never name what the platform is built from"),
            ("removed names", removed, "these no longer exist: delete the line or describe what replaced it"),
            ("links", broken, note)):
        out.append(f"  {title}: {len(found)} finding{'' if len(found) == 1 else 's'} ({hint})")
        out += [f"    {line}" for line in found]
    if skipped:
        out.append(f"  {skipped}")
    return "\n".join(out), len(words) + len(removed) + len(broken)


def on_pre_build(config, **kwargs):
    """mkdocs hook of kaos-lib: a finding, or a trunk that cannot be downloaded, stops the build."""
    from mkdocs.exceptions import PluginError
    try:
        self_test()
        report, findings = run(find_root(pathlib.Path(config["config_file_path"]).resolve().parent))
    except SystemExit as exc:
        raise PluginError(str(exc)) from None
    print(report)
    if findings:
        raise PluginError(f"docs check: {findings} findings, listed above")


# ------------------------------------------------------------------ the checker's own cases
def self_test() -> int:
    """Every rule on a small made-up copy of the three repositories; an AssertionError names the case that broke."""
    global HERE
    top = pathlib.Path(tempfile.mkdtemp(prefix="docs-check-self-"))
    kept = HERE
    try:
        for key, spec in REPOS.items():
            (top / key / "docs" / "img").mkdir(parents=True)
            (top / key / "mkdocs.yml").write_text(f"repo_name: {spec['repo']}\nnav:\n  - Home: index.md\n")
            (top / key / "docs" / "index.md").write_text("# Home\n\n## A heading\n")
            (top / key / "docs" / "img" / "argo-run.png").write_bytes(b"")
        (top / "KAOS_LIB" / "docs_check.py").write_text("line\n")
        (top / "YOLO" / "docs" / "into-hera.md").write_text("[gone](https://novelcore.github.io/hera-pipeline-template/gone/)\n")
        lines = [
            "Open Argo.", "The argoproj project.", "Set ARGO_SERVER first.", '[the form](index.md "the Argo form")',
            "Run kubectl.", "In the namespace.", "Crossplane makes it.", "On kubecore-dev-kaos-v3-gke.",          # 1-8: words
            "[Hera](https://github.com/argoproj-labs/hera) and ![a run](img/argo-run.png) are fine.",              # 9: not words
            "The dataset-loading step.", "steps/data_summary/", "compose_and_validate",
            "`./kubecore/compose.py`", "<app>/kubecore/x.py", "my-app/kubecore/", "the kubecore folder", "a `kubecore/` copy",  # 10-17
            "`src/kubecore/`, `.kubecore/dataset-config.yaml`, `~/.cache/kubecore/datasets` are fine.",          # 18: allowed
            "[no file](nope.md)", "[no heading](index.md#nope)", '<a href="nope-a.md">x</a>', '<img src="img/nope.png">',
            "[![a run](img/argo-run.png)](nope-outer.md)",
            "[no page](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/nope.html)",
            "[no heading there](https://novelcore.github.io/yolo-pipelines-template/#nope)",                    # 19-25: links
            "[ok](index.md#a-heading) <a href=\"index.md\">ok</a> [![a run](img/argo-run.png)](index.md)",
            "[lines](https://github.com/kaos-io/kaos-lib/blob/main/docs_check.py#L3-L9) "
            "[line](https://github.com/kaos-io/kaos-lib/blob/main/docs_check.py#L1)",
            "[ok there](https://storage.googleapis.com/kaos-dev-511509-kaos-lib/docs/index.html#a-heading)",      # 26-28: fine
        ]
        (top / "HERA" / "docs" / "page.md").write_text("\n".join(lines) + "\n")
        env = {f"DOCS_CHECK_{key}": str(top / key) for key in REPOS}
        words, removed = check_text(top / "HERA", "HERA")
        broken, _, skipped = check_links(top / "HERA", "HERA", env)
        at = lambda found: sorted({int(f.split(":")[1]) for f in found if f.startswith("docs/page.md:")})
        assert at(words) == [1, 2, 3, 4, 5, 6, 7, 8], f"words: {words}"
        assert at(removed) == [10, 11, 12, 13, 14, 15, 16, 17], f"removed names: {removed}"
        assert at(broken) == [19, 20, 21, 22, 23, 24, 25], f"links: {broken}"
        assert sum("into-hera.md:1 links to" in f for f in broken) == 1 and not skipped, f"inbound: {broken}"
        _, _, skipped = check_links(top / "HERA", "HERA", {"DOCS_CHECK_OFFLINE": "1"})
        assert skipped.startswith("SKIPPED (DOCS_CHECK_OFFLINE=1): 5 links"), f"offline: {skipped}"
        HERE = top / "nowhere"                                   # no kaos-lib checkout: it must be downloaded
        REPOS["KAOS_LIB"]["trunk"], real = "no-such-branch-docs-check-self-test", REPOS["KAOS_LIB"]["trunk"]
        try:
            failed = ""
            try:
                with _no_network():
                    check_links(top / "HERA", "HERA", {"DOCS_CHECK_YOLO": str(top / "YOLO")})
            except SystemExit as exc:
                failed = str(exc)
        finally:
            REPOS["KAOS_LIB"]["trunk"] = real
        assert "cannot download kaos-io/kaos-lib" in failed and "DOCS_CHECK_OFFLINE=1" in failed, f"fail closed: {failed!r}"
    finally:
        HERE = kept
        shutil.rmtree(top, True)
    return 0


class _no_network:
    """Downloads fail at once inside the block."""
    def __enter__(self):
        self.open, self.sleep = urllib.request.urlopen, time.sleep
        def refuse(*a, **k):
            raise urllib.error.URLError("no network (self-test)")
        urllib.request.urlopen, time.sleep = refuse, lambda s: None

    def __exit__(self, *exc):
        urllib.request.urlopen, time.sleep = self.open, self.sleep


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        self_test()
        print("docs check self-test: ok")
        sys.exit(0)
    text, count = run(find_root(pathlib.Path(sys.argv[1] if sys.argv[1:] else HERE).resolve()))
    print(text)
    sys.exit(1 if count else 0)
