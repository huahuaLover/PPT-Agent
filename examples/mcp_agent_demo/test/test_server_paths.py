"""Workspace path protection tests for MCP tools."""

from pathlib import Path

import pytest

import server


def test_resolve_workspace_path_rejects_escape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORKSPACE", str(tmp_path))

    with pytest.raises(ValueError, match="outside workspace"):
        server.resolve_workspace_path("../outside.txt")


def test_write_and_read_file_inside_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORKSPACE", str(tmp_path))

    assert server.write_file.fn("notes/example.txt", "hello") == "notes/example.txt"
    assert server.read_file.fn("notes/example.txt") == "hello"
