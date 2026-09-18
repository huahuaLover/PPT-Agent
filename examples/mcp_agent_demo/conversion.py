"""Deterministic export from inspected HTML slides to PPTX and PDF."""

import shutil
import traceback
from pathlib import Path
from typing import Literal

from deeppresenter.utils.webview import PlaywrightConverter, convert_html_to_pptx
from pptx import Presentation
from pypdf import PdfReader

from models import ExportResult


def validate_slide_files(
    slides_dir: Path,
    workspace: Path,
    expected_pages: int,
) -> list[Path]:
    """Return a complete, ordered slide list inside the workspace."""
    slides_dir = slides_dir.resolve()
    workspace = workspace.resolve()
    if not slides_dir.is_relative_to(workspace) or not slides_dir.is_dir():
        raise ValueError("slides_dir must be a directory inside the workspace")
    expected_names = [
        f"slide_{index:02d}.html" for index in range(1, expected_pages + 1)
    ]
    html_files = sorted(slides_dir.glob("*.html"))
    actual_names = [path.name for path in html_files]
    if actual_names != expected_names:
        raise ValueError(
            f"Expected slide files {expected_names}, but found {actual_names}"
        )
    return html_files


async def export_slides(
    slides_dir: Path,
    workspace: Path,
    expected_pages: int,
    aspect_ratio: Literal["16:9"],
    soft_parsing: bool,
) -> ExportResult:
    """Export HTML slides, using PDF as the fallback when PPTX conversion fails."""
    workspace = workspace.resolve()
    slides_dir = slides_dir.resolve()
    html_files = validate_slide_files(slides_dir, workspace, expected_pages)
    pptx_path = workspace / "result.pptx"
    pdf_path = workspace / "result.pdf"
    preview_dir = workspace / "previews"
    preview_dir.mkdir(exist_ok=True)

    pptx_error: str | None = None
    try:
        await convert_html_to_pptx(
            slides_dir,
            pptx_path,
            aspect_ratio=aspect_ratio,
            soft_parsing=soft_parsing,
        )
        if not pptx_path.is_file() or pptx_path.stat().st_size == 0:
            raise RuntimeError("HTML conversion did not create result.pptx")
        if len(Presentation(pptx_path).slides) != expected_pages:
            raise RuntimeError("Generated PPTX page count does not match the request")
    except Exception as error:
        pptx_error = str(error)
        (workspace / ".html2pptx-error.txt").write_text(
            f"{error}\n{traceback.format_exc()}", encoding="utf-8"
        )
        pptx_path = None

    image_dir: Path | None = None
    try:
        async with PlaywrightConverter() as converter:
            image_dir = await converter.convert_to_pdf(
                html_files,
                pdf_path,
                aspect_ratio,
            )
        if len(PdfReader(pdf_path).pages) != expected_pages:
            raise RuntimeError("Generated PDF page count does not match the request")
        for image_path in sorted(image_dir.glob("slide_*.jpg")):
            shutil.copy2(image_path, preview_dir / image_path.name)
    finally:
        await PlaywrightConverter.shutdown()
        if image_dir is not None and image_dir.is_dir():
            shutil.rmtree(image_dir)

    final_path = pptx_path if pptx_path is not None else pdf_path
    return ExportResult(
        final_path=final_path,
        pptx_path=pptx_path,
        pdf_path=pdf_path,
        preview_dir=preview_dir,
        pptx_error=pptx_error,
    )
