"""Unit tests for ui_attr_audit.py."""

import json
from pathlib import Path

from scripts.ui_attr_audit import extract_template_attrs, make_snapshot, run_check, to_item_set


def test_extract_and_to_item_set():
    html = """
    <div id="test-id" name="test-name" for="test-for">
      <button hx-get="/api/items" onclick="doAction( 1, 2 )" data-item-id="42">Click</button>
      <a href="/preview/candidates/{{ item.id }}">Detail</a>
      {% include "_partial.html" %}
      <span>{{ t("common.submit") }}</span>
      <script>console.log("hello");</script>
    </div>
    """
    attrs = extract_template_attrs(html)
    assert "test-id" in attrs["ids"]
    assert "test-name" in attrs["names"]
    assert "test-for" in attrs["fors"]
    assert "hx-get:/api/items" in attrs["hx_attrs"]
    assert "onclick:doAction( 1, 2 )" in attrs["on_attrs"]
    assert "data-item-id:42" in attrs["data_attrs"]
    assert "href:/preview/candidates/{{ item.id }}" in attrs["urls"]
    assert '{% include "_partial.html" %}' in attrs["jinja_tags"]
    assert "common.submit" in attrs["t_keys"]
    assert len(attrs["script_hashes"]) == 1

    items = to_item_set(attrs)
    assert "id:test-id" in items
    assert "name:test-name" in items
    assert "for:test-for" in items
    assert "hx-get:/api/items" in items
    assert "onclick:doAction( 1, 2 )" in items
    assert "data-item-id:42" in items
    assert "href:/preview/candidates/{{ item.id }}" in items
    assert 'jinja:{% include "_partial.html" %}' in items
    assert "t:common.submit" in items


def test_audit_workflow_with_tmp_dir(tmp_path: Path):
    tpl_dir = tmp_path / "templates"
    tpl_dir.mkdir()
    tpl_file = tpl_dir / "sample.html"
    tpl_file.write_text('<div id="btn1" name="box1"><a href="/test">Link</a></div>', encoding="utf-8")

    baseline_file = tmp_path / "baseline.json"
    allowlist_file = tmp_path / "allowlist.json"
    allowlist_file.write_text("{}", encoding="utf-8")

    # 1. Snapshot
    make_snapshot(tpl_dir, baseline_file)
    assert baseline_file.exists()

    # 2. Check identical -> PASS
    assert run_check(tpl_dir, baseline_file, allowlist_file) is True

    # 3. Add an attribute -> PASS (additions are OK)
    tpl_file.write_text('<div id="btn1" name="box1" data-extra="ok"><a href="/test">Link</a></div>', encoding="utf-8")
    assert run_check(tpl_dir, baseline_file, allowlist_file) is True

    # 4. Remove an attribute without allowlist -> FAIL
    tpl_file.write_text('<div name="box1"><a href="/test">Link</a></div>', encoding="utf-8")
    assert run_check(tpl_dir, baseline_file, allowlist_file) is False

    # 5. Add missing item to allowlist -> PASS
    allowlist_data = {"sample.html": ["id:btn1"]}
    allowlist_file.write_text(json.dumps(allowlist_data), encoding="utf-8")
    assert run_check(tpl_dir, baseline_file, allowlist_file) is True
