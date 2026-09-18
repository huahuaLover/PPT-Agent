"""Inspection state and freshness tests."""

import json
from pathlib import Path

import pytest

import server


def create_slide_set(workspace: Path) -> Path:
    slides = workspace / "slides"
    slides.mkdir()
    (slides / "global.css").write_text("body { color: black; }", encoding="utf-8")
    for page in (1, 2):
        (slides / f"slide_{page:02d}.html").write_text(
            f"<html><body><p>Page {page}</p></body></html>",
            encoding="utf-8",
        )
    return slides


def test_finalize_requires_every_slide_to_be_inspected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORKSPACE", str(tmp_path))
    slides = create_slide_set(tmp_path)

    with pytest.raises(ValueError, match="has not passed"):
        server.validate_slides_directory(slides, expected_pages=2)


def test_css_change_invalidates_previous_inspections(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORKSPACE", str(tmp_path))
    slides = create_slide_set(tmp_path)
    state = {
        path.name: {
            "status": "passed",
            "attempts": 1,
            "sha256": server.slide_digest(path),
        }
        for path in sorted(slides.glob("*.html"))
    }
    (slides / ".inspection.json").write_text(json.dumps(state), encoding="utf-8")
    server.validate_slides_directory(slides, expected_pages=2)

    (slides / "global.css").write_text("body { color: blue; }", encoding="utf-8")

    with pytest.raises(ValueError, match="changed after inspect_slide"):
        server.validate_slides_directory(slides, expected_pages=2)
