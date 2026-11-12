"""The Dockerfile doctor (PRD-CONSOLE-1682 AC-40): each rule L-D01 .. L-D08 fires on its own fixture and is silent on
the clean twin, with a fix and a documentation page; plus the parser facts the rules stand on."""
import pathlib

import pytest

from kaos_lib.lint import dockerfile as df
from kaos_lib.lint import lint_project
from lint_corpus import write_repo

DOCS = pathlib.Path(__file__).resolve().parent.parent / "docs" / "lint"
PIPE = 'from kubecore.authoring import pipeline, step\n\nwith pipeline("p") as p:\n    a = step("work", kind="evaluate"%s)\n'
ENTRY = "app/entry.py"
GOOD = ('FROM python:3.11-slim\nWORKDIR /app\nARG KAOS_LIB_PACKAGE="kaos-lib==0.4.0"\n'
        'RUN pip install --no-cache-dir "${KAOS_LIB_PACKAGE}"\nCOPY app/ ./app/\nENTRYPOINT ["python", "-m", "app.entry"]\n')
DRIVER_ENV = "ENV LD_LIBRARY_PATH=/usr/local/nvidia/lib64:/usr/local/nvidia/lib\nENV PATH=/usr/local/nvidia/bin:${PATH}\n"
GOOD_GPU = GOOD.replace("WORKDIR /app\n", "WORKDIR /app\n" + DRIVER_ENV).replace(
    "kaos-lib==0.4.0\"\n", "kaos-lib==0.4.0\"\nRUN pip install --no-cache-dir torch\n")
GPU_NO_PATH = GOOD.replace("kaos-lib==0.4.0\"\n", "kaos-lib==0.4.0\"\nRUN pip install --no-cache-dir torch\n")
USES_LIB = "from kaos_lib import datasets\n"


def repo(dockerfile=GOOD, code=USES_LIB, gpu=False, extra=None, entry=True):
    files = {"pipeline.py": PIPE % (", gpu=True" if gpu else ""), "steps/work/Dockerfile": dockerfile}
    if entry:
        files["steps/work/" + ENTRY] = code
    files.update(extra or {})
    return files


# rule -> (failing, clean twin, expected line of the finding, substring of the message, level)
CASES = {
    "L-D01": (repo(GOOD.replace('ARG KAOS_LIB_PACKAGE="kaos-lib==0.4.0"\n', "").replace("${KAOS_LIB_PACKAGE}", "kaos-lib==0.4.0")),
              repo(), 3, "does not declare ARG KAOS_LIB_PACKAGE", "error"),
    "L-D02": (repo(GOOD.replace("${KAOS_LIB_PACKAGE}", "requests")), repo(), 3, "installs", "error"),
    "L-D03": (repo(GOOD.replace("FROM python", "FROM --platform=linux/arm64 python")), repo(), 1, "linux/arm64", "error"),
    "L-D04": (repo(GOOD + "COPY /etc/passwd /x\n"), repo(), 7, "absolute path", "error"),
    "L-D05": (repo(entry=False), repo(), 1, "no steps/work/app/entry.py", "error"),
    "L-D06": (repo(GOOD.replace("--no-cache-dir ", "")), repo(), 4, "--no-cache-dir", "warning"),
    "L-D07": (repo(), repo(GOOD.replace("ENTRYPOINT", "USER app\nENTRYPOINT")), 1, "runs as root", "info"),
    "L-D08": (repo(code="x = 1\n", gpu=True), repo(code="x = 1\n", gpu=True, dockerfile=GOOD_GPU), 1, "no CUDA", "warning"),
}


def findings(tmp_path, files, rule_id):
    report = lint_project(write_repo(tmp_path, files))
    return [f for f in report.findings if f.rule == rule_id]


@pytest.mark.parametrize("rule_id", sorted(CASES))
def test_should_fire_on_its_fixture_and_stay_silent_on_the_clean_twin(rule_id, tmp_path):
    failing, clean, line, text, level = CASES[rule_id]
    hit = findings(tmp_path / "fail", failing, rule_id)
    assert hit, f"{rule_id} did not fire"
    assert hit[0].level == level and hit[0].span.line == line and text in hit[0].message
    assert hit[0].file == "steps/work/Dockerfile" and hit[0].fix and hit[0].doc.endswith(f"/{rule_id}.html")
    assert not findings(tmp_path / "pass", clean, rule_id)


@pytest.mark.parametrize("rule_id", sorted(CASES))
def test_should_have_a_documentation_page(rule_id):
    assert (DOCS / f"{rule_id}.md").read_text().count(rule_id) >= 1


def test_should_stay_silent_on_a_clean_repository_apart_from_the_root_user_info(tmp_path):
    report = lint_project(write_repo(tmp_path, repo()))
    assert [f.rule for f in report.findings if f.rule.startswith("L-D")] == ["L-D07"]


def test_should_not_judge_a_step_that_has_no_dockerfile(tmp_path):
    files = repo()
    del files["steps/work/Dockerfile"]
    assert not [f for f in lint_project(write_repo(tmp_path, files)).findings if f.rule.startswith("L-D")]


def test_should_not_demand_the_kaos_lib_arg_of_a_step_that_never_uses_kaos_lib(tmp_path):
    plain = repo("FROM python:3.11-slim\nRUN pip install --no-cache-dir PyYAML\nCOPY app/ ./app/\n"
                 'ENTRYPOINT ["python", "-m", "app.entry"]\n', code="import yaml\n")
    assert not [f for f in findings(tmp_path, plain, "L-D01")]


def test_should_warn_when_the_entrypoint_is_not_python_dash_m_app_entry(tmp_path):
    hit = findings(tmp_path, repo(GOOD.replace('["python", "-m", "app.entry"]', '["python", "train.py"]')), "L-D05")
    assert [(f.level, f.span.line) for f in hit] == [("warning", 6)]


def test_should_flag_a_copy_source_that_does_not_exist_in_the_context(tmp_path):
    hit = findings(tmp_path, repo(GOOD + "COPY shared/ ./shared/\n"), "L-D04")
    assert "does not exist in the build context" in hit[0].message


def test_should_allow_the_compose_step_to_copy_from_the_repository_root(tmp_path):
    compose = ("FROM python:3.11-slim\nCOPY kubecore/ ./kubecore/\nCOPY config/ ./config/\n"
               'ENTRYPOINT ["python", "-m", "kubecore.compose"]\n')
    files = repo(extra={"steps/compose_and_validate/Dockerfile": compose, "kubecore/__init__.py": "", "config/a.yaml": "a: 1\n"})
    assert not findings(tmp_path, files, "L-D04") and not findings(tmp_path, files, "L-D05")


def test_should_warn_about_copying_the_whole_repository_root_into_the_compose_image(tmp_path):
    compose = "FROM python:3.11-slim\nCOPY . .\n"
    hit = findings(tmp_path, repo(extra={"steps/compose_and_validate/Dockerfile": compose}), "L-D06")
    assert "COPY . ." in hit[0].message


def test_should_warn_about_apt_without_cleanup_and_stay_silent_with_it(tmp_path):
    bad = GOOD + "RUN apt-get update && apt-get install -y gcc\n"
    ok = GOOD + "RUN apt-get update && apt-get install -y gcc && rm -rf /var/lib/apt/lists/*\n"
    assert findings(tmp_path / "a", repo(bad), "L-D06") and not findings(tmp_path / "b", repo(ok), "L-D06")


def test_should_accept_a_cuda_base_image_for_a_gpu_step(tmp_path):
    cuda = GOOD.replace("python:3.11-slim", "nvidia/cuda:12.2.0-runtime-ubuntu22.04")
    assert not findings(tmp_path, repo(cuda, code="x = 1\n", gpu=True), "L-D08")


def test_should_warn_when_a_gpu_step_on_a_plain_base_does_not_set_the_driver_path(tmp_path):
    hit = findings(tmp_path, repo(GPU_NO_PATH, code="x = 1\n", gpu=True), "L-D08")
    assert len(hit) == 1 and hit[0].level == "warning" and hit[0].file == "steps/work/Dockerfile"
    assert "does not set the NVIDIA driver path" in hit[0].message
    assert "platform adds the path on its own GPU machines" in hit[0].message


def test_should_accept_the_driver_path_on_a_plain_base(tmp_path):
    assert not findings(tmp_path, repo(GOOD_GPU, code="x = 1\n", gpu=True), "L-D08")


def test_should_not_ask_a_cuda_base_for_the_driver_path(tmp_path):
    cuda = GPU_NO_PATH.replace("python:3.11-slim", "nvidia/cuda:12.2.0-runtime-ubuntu22.04")
    assert not findings(tmp_path, repo(cuda, code="x = 1\n", gpu=True), "L-D08")


def test_should_not_judge_the_driver_path_of_a_cpu_step(tmp_path):
    assert not findings(tmp_path, repo(GPU_NO_PATH, code="x = 1\n", gpu=False), "L-D08")


def test_should_say_only_the_missing_cuda_when_both_would_apply(tmp_path):
    hit = findings(tmp_path, repo(GOOD, code="x = 1\n", gpu=True), "L-D08")
    assert len(hit) == 1 and "no CUDA support" in hit[0].message


# --- the parser the rules stand on ------------------------------------------------------------------------------

def test_parser_should_join_continuations_and_skip_comments():
    ins = df.parse("# c\nRUN pip install \\\n  # inner\n  a==1 \\\n  b==2\nCOPY x y\n")
    assert [(i.keyword, i.line, i.end_line) for i in ins] == [("RUN", 2, 5), ("COPY", 6, 6)]
    assert df.pip_installs(ins)[0].specs == ["a==1", "b==2"]


def test_parser_should_read_pip_options_and_files():
    ins = df.parse('RUN python -m pip install --no-cache-dir -r requirements.txt --extra-index-url https://x/simple "a>=1,<2" && echo hi\n')
    pip = df.pip_installs(ins)[0]
    assert (pip.specs, pip.files, pip.index_options, pip.no_cache_dir) == \
        (["a>=1,<2"], ["requirements.txt"], [("--extra-index-url", "https://x/simple")], True)


@pytest.mark.parametrize("image,expected", [("python:3.11-slim", "3.11"), ("python:3.12.4-bookworm", "3.12"),
                                            ("docker.io/library/python:3.10", "3.10"), ("ubuntu:22.04", None)])
def test_parser_should_read_the_python_version_of_the_base_image(image, expected):
    assert df.python_version(image) == expected
