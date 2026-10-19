import pytest

from core.schemas import ExperimentFile, SourceEdit
from services.workspace import (
    EditError,
    WorkspaceManager,
    add_files,
    apply_edits,
    is_test_path,
    safe_relative,
)


def test_apply_edit_produces_unified_diff(demo_copy):
    result = apply_edits(
        demo_copy,
        [
            SourceEdit(
                file="src/domain/status.ts",
                search="  return allowed.length === 0 || allowed.includes(to);",
                replace="  return allowed.includes(to);",
            )
        ],
        allow_test_files=False,
        allow_create=False,
    )
    assert "-  return allowed.length === 0 || allowed.includes(to);" in result.diff
    assert "+  return allowed.includes(to);" in result.diff
    assert result.files_changed()[0] == {
        "path": "src/domain/status.ts",
        "added": 1,
        "removed": 1,
        "created": False,
    }
    assert "allowed.length === 0" not in (demo_copy / "src/domain/status.ts").read_text()


def test_repairs_cannot_touch_tests(demo_copy):
    with pytest.raises(EditError, match="test files"):
        apply_edits(
            demo_copy,
            [SourceEdit(file="test/status.test.ts", search="assert", replace="//")],
            allow_test_files=False,
            allow_create=False,
        )


@pytest.mark.parametrize(
    "path", ["../outside.ts", "/etc/passwd", "C:/Windows/x", "src/../../x.ts", ".git/config"]
)
def test_path_traversal_is_rejected(demo_copy, path):
    with pytest.raises(EditError):
        safe_relative(demo_copy, path)


def test_ambiguous_and_missing_search(demo_copy):
    with pytest.raises(EditError, match="more than once"):
        apply_edits(
            demo_copy,
            [SourceEdit(file="src/services/orderService.ts", search="order", replace="x")],
            allow_test_files=False,
            allow_create=False,
        )
    with pytest.raises(EditError, match="not found"):
        apply_edits(
            demo_copy,
            [SourceEdit(file="src/services/orderService.ts", search="nope nope", replace="x")],
            allow_test_files=False,
            allow_create=False,
        )


def test_crlf_tolerant_match(tmp_path):
    (tmp_path / "a.ts").write_bytes(b"line one  \r\nline two\r\n")
    result = apply_edits(
        tmp_path,
        [SourceEdit(file="a.ts", search="line one\nline two", replace="merged")],
        allow_test_files=False,
        allow_create=False,
    )
    assert result.changes
    assert (tmp_path / "a.ts").read_bytes() == b"merged\r\n"


def test_create_new_file_only_with_empty_search(demo_copy):
    result = apply_edits(
        demo_copy,
        [SourceEdit(file="src/lib/new.ts", search="", replace="export const x = 1;\n")],
        allow_test_files=False,
        allow_create=True,
    )
    assert result.changes[0].created
    assert "/dev/null" in result.diff
    with pytest.raises(EditError):
        apply_edits(
            demo_copy,
            [SourceEdit(file="src/app.ts", search="", replace="boom")],
            allow_test_files=False,
            allow_create=True,
        )


def test_experiment_files_must_be_new(demo_copy):
    written = add_files(demo_copy, [ExperimentFile(path="test/forge-experiments/E1.test.ts", content="x")])
    assert written == ["test/forge-experiments/E1.test.ts"]
    with pytest.raises(EditError, match="already exists"):
        add_files(demo_copy, [ExperimentFile(path="test/status.test.ts", content="x")])


def test_is_test_path():
    assert is_test_path("test/orders.test.ts")
    assert is_test_path("src/foo.spec.js")
    assert is_test_path("tests/test_api.py")
    assert not is_test_path("src/services/orderService.ts")


def test_workspace_copies_are_disposable(tmp_path, demo_copy):
    manager = WorkspaceManager(tmp_path / "ws")
    ws = manager.create(demo_copy, "inv1", "exp E1")
    assert (ws / "src/app.ts").exists()
    (ws / "src/app.ts").write_text("changed")
    assert (demo_copy / "src/app.ts").read_text() != "changed"
    manager.cleanup("inv1")
    assert not ws.exists()
