"""Deterministic export input validation tests."""

from pathlib import Path

import pytest

from conversion import validate_slide_files


def test_validate_slide_files_returns_ordered_pages(tmp_path: Path) -> None:
    slides = tmp_path / "slides"
    slides.mkdir()
    for page in (2, 1):
        (slides / f"slide_{page:02d}.html").write_text("<html></html>")

    result = validate_slide_files(slides, tmp_path, expected_pages=2)

    assert [path.name for path in result] == ["slide_01.html", "slide_02.html"]


def test_validate_slide_files_rejects_page_gap(tmp_path: Path) -> None:
    slides = tmp_path / "slides"
    slides.mkdir()
    (slides / "slide_01.html").write_text("<html></html>")
    (slides / "slide_03.html").write_text("<html></html>")

    with pytest.raises(ValueError, match="Expected slide files"):
        validate_slide_files(slides, tmp_path, expected_pages=2)
