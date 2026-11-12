"""The guide shows files from copies under docs/examples/. The copies must equal the templates, byte for byte.

Point DOCS_CHECK_HERA and DOCS_CHECK_YOLO at checkouts of hera-pipeline-template and yolo-pipelines-template (branch
dev). A test without its variable is skipped.
"""
import os
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).resolve().parents[1] / "docs" / "examples"
HERA, YOLO = os.environ.get("DOCS_CHECK_HERA"), os.environ.get("DOCS_CHECK_YOLO")


def shown(root: Path) -> set:
    files = {"pipeline.py", *(p.relative_to(root).as_posix() for p in (root / "config").glob("*.yaml"))}
    return files | {p.relative_to(root).as_posix() for p in (root / "steps").glob("*/app/entry.py")}


@pytest.mark.skipif(not HERA, reason="set DOCS_CHECK_HERA to a checkout of the hera template")
def test_should_equal_the_hera_template_the_guide_builds_its_first_ten_pages_on():
    copy, template = EXAMPLES / "first-pipeline" / "template", Path(HERA)
    assert shown(copy) == shown(template), "the guide shows other files than the template holds"
    different = [name for name in sorted(shown(template)) if (copy / name).read_bytes() != (template / name).read_bytes()]
    assert not different, f"these files differ from docs/examples/first-pipeline/template: {different}"


@pytest.mark.skipif(not YOLO, reason="set DOCS_CHECK_YOLO to a checkout of the yolo template")
@pytest.mark.parametrize("name", ("pipeline.py", "steps/prepare_data/app/entry.py"))
def test_should_equal_the_yolo_files_the_page_a_real_pipeline_shows(name):
    assert (EXAMPLES / "yolo-pipeline" / name).read_bytes() == (Path(YOLO) / name).read_bytes(), name
