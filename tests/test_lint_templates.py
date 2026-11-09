"""The two pipeline templates' current pipeline.py produce no lint errors (PRD-CONSOLE-1682 AC-22).

The templates are private repositories, so they are not copied here: set KAOS_LINT_TEMPLATES to a folder holding
clones of hera-pipeline-template and yolo-pipelines-template (branch dev). Without it these tests are skipped.
"""
import os
import pathlib

import pytest

from kaos_lib.lint import default_catalogue, lint_project, read_context

ROOT = os.environ.get("KAOS_LINT_TEMPLATES")
TEMPLATES = ("hera-pipeline-template", "yolo-pipelines-template")

pytestmark = pytest.mark.skipif(not ROOT, reason="set KAOS_LINT_TEMPLATES to a folder with both template clones")


@pytest.mark.parametrize("name", TEMPLATES)
def test_should_report_no_errors_on_the_template(name):
    report = lint_project(pathlib.Path(ROOT) / name, default_catalogue())
    assert report.errors == 0, report.to_json()


@pytest.mark.parametrize("name", TEMPLATES)
def test_should_report_no_errors_with_the_templates_local_context(name):
    template = pathlib.Path(ROOT) / name
    catalogue = read_context(str(template / "kubecore" / "local-dev" / "pipeline-context.yaml"))
    assert lint_project(template, catalogue).errors == 0
