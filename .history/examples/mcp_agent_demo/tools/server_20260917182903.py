"""FastMCP tools used by the HTML slide generation demo."""

import asyncio
import base64
import hashlib
import json
import os
import re
import shutil
import tempfile
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from deeppresenter.utils.webview import (
    PlaywrightConverter,
    convert_html_to_pptx,
    playwright_lifespan,
)
from fastmcp import FastMCP
from mcp.types import ImageContent, TextContent
from PIL import Image
from tavily import TavilyClient

from stdio_compat import install_if_needed


mcp = FastMCP("MCP Agent Demo Tools", lifespan=playwright_lifespan)
MAX_FILE_CHARS = 200_000
MAX_PATH_CHARS = 512
MAX_DOWNLOAD_BYTES = 10 * 1024 * 1024
SLIDE_NAME = re.compile(r"slide_(\d{2})\.html")


def get_workspace() -> Path:
    """Return the configured task workspace."""
    raw_workspace = os.environ.get("WORKSPACE")
    if not raw_workspace:
        raise RuntimeError("WORKSPACE environment variable is required")
    workspace = Path(raw_workspace).resolve()
    if not workspace.is_dir():
        raise RuntimeError(f"Workspace does not exist: {workspace}")
    return workspace


def resolve_workspace_path(raw_path: str) -> Path:
    """Resolve a path and ensure it cannot escape the task workspace."""
    if not raw_path.strip():
        raise ValueError("Path cannot be empty")
    if "\n" in raw_path or len(raw_path) > MAX_PATH_CHARS:
        raise ValueError("Expected a file path, but received long-form text")
    workspace = get_workspace()
    path = Path(raw_path)
    candidate = path.resolve() if path.is_absolute() else (workspace / path).resolve()
    if not candidate.is_relative_to(workspace):
        raise ValueError(f"Path is outside workspace: {raw_path}")
    return candidate


def relative_path(path: Path) -> str:
    """Return a stable POSIX path relative to the task workspace."""
    return path.resolve().relative_to(get_workspace()).as_posix()


def get_tavily_client() -> TavilyClient:
    """Build a Tavily client from the MCP process environment."""
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        raise RuntimeError("Tavily API key was not provided by the MCP client")
    return TavilyClient(api_key=api_key)


@mcp.tool()
async def search_web(query: str, max_results: int = 5) -> str:
    """Search the web and return concise results with source URLs."""
    query = query.strip()
    if not query:
        raise ValueError("Search query cannot be empty")

    configured_limit = int(os.environ.get("SEARCH_MAX_RESULTS", "5"))
    content_limit = int(os.environ.get("SEARCH_MAX_CONTENT_CHARS", "1500"))
    effective_limit = min(max(max_results, 1), configured_limit, 10)
    response = await asyncio.to_thread(
        get_tavily_client().search,
        query=query,
        search_depth="basic",
        max_results=effective_limit,
        include_answer=False,
        include_raw_content=False,
    )
    results = [
        {
            "title": str(item.get("title", "")),
            "url": str(item.get("url", "")),
            "content": str(item.get("content", ""))[:content_limit],
        }
        for item in response.get("results", [])
    ]
    return json.dumps({"query": query, "results": results}, ensure_ascii=False)


@mcp.tool()
async def search_images(query: str, max_results: int = 4) -> str:
    """Search for relevant images and return URLs with descriptions."""
    query = query.strip()
    if not query:
        raise ValueError("Image search query cannot be empty")
    configured_limit = int(os.environ.get("SEARCH_MAX_IMAGE_RESULTS", "4"))
    effective_limit = min(max(max_results, 1), configured_limit, 8)
    response = await asyncio.to_thread(
        get_tavily_client().search,
        query=query,
        max_results=effective_limit,
        include_images=True,
        include_image_descriptions=True,
        include_raw_content=False,
    )

    images: list[dict[str, str]] = []
    for item in response.get("images", []):
        if isinstance(item, str):
            url, description = item, ""
        elif isinstance(item, dict):
            url = str(item.get("url", ""))
            description = str(item.get("description", ""))
        else:
            continue
        if urlparse(url).scheme in {"http", "https"}:
            images.append({"url": url, "description": description})
        if len(images) == effective_limit:
            break
    return json.dumps({"query": query, "images": images}, ensure_ascii=False)


@mcp.tool()
async def download_file(url: str, output_path: str) -> str:
    """Download and validate an image inside the workspace assets directory."""
    if urlparse(url).scheme not in {"http", "https"}:
        raise ValueError("Only HTTP(S) image URLs are allowed")
    destination = resolve_workspace_path(output_path)
    assets_dir = get_workspace() / "assets"
    if not destination.is_relative_to(assets_dir):
        raise ValueError("Downloaded images must be saved under assets/")
    if destination.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise ValueError("Image path must end with .png, .jpg, .jpeg, or .webp")

    data = bytearray()
    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > MAX_DOWNLOAD_BYTES:
                    raise ValueError("Image download exceeds 10 MB")

    with Image.open(BytesIO(data)) as image:
        image.verify()
    with Image.open(BytesIO(data)) as image:
        image.load()
        width, height = image.size
        if destination.suffix.lower() == ".webp":
            destination = destination.with_suffix(".png")
        save_format = "PNG" if destination.suffix.lower() == ".png" else "JPEG"
        if save_format == "JPEG" and image.mode not in {"RGB", "L"}:
            image = image.convert("RGB")
        destination.parent.mkdir(parents=True, exist_ok=True)
        image.save(destination, format=save_format)

    result = {
        "path": relative_path(destination),
        "width": width,
        "height": height,
        "source_url": url,
    }
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def read_file(path: str) -> str:
    """Read a UTF-8 text file from the task workspace."""
    file_path = resolve_workspace_path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"File does not exist: {path}")
    content = file_path.read_text(encoding="utf-8")
    if len(content) > MAX_FILE_CHARS:
        raise ValueError(f"File is too large to read: {path}")
    return content


@mcp.tool()
def write_file(path: str, content: str) -> str:
    """Write UTF-8 text to a file inside the task workspace."""
    if len(content) > MAX_FILE_CHARS:
        raise ValueError(f"File is too large to write: {path}")
    file_path = resolve_workspace_path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")
    return relative_path(file_path)


def inspection_path() -> Path:
    """Return the persistent per-slide inspection state path."""
    return get_workspace() / "slides" / ".inspection.json"


def load_inspection_state() -> dict[str, dict[str, Any]]:
    """Load inspection state, or return an empty state before the first check."""
    path = inspection_path()
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("slides/.inspection.json must contain a JSON object")
    return data


def save_inspection_state(state: dict[str, dict[str, Any]]) -> None:
    """Atomically persist inspection state."""
    path = inspection_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


def slide_digest(html_path: Path) -> str:
    """Hash one slide together with the shared stylesheet."""
    css_path = html_path.parent / "global.css"
    if not css_path.is_file() or css_path.stat().st_size == 0:
        raise FileNotFoundError("slides/global.css does not exist or is empty")
    return hashlib.sha256(
        html_path.read_bytes() + b"\0" + css_path.read_bytes()
    ).hexdigest()


def validate_slide_path(html_file: str, expected_pages: int) -> tuple[Path, int]:
    """Validate the slide location, name, and requested page range."""
    if not 2 <= expected_pages <= 20:
        raise ValueError("expected_pages must be between 2 and 20")
    html_path = resolve_workspace_path(html_file)
    if html_path.parent != get_workspace() / "slides" or not html_path.is_file():
        raise ValueError("html_file must be an existing file directly under slides/")
    match = SLIDE_NAME.fullmatch(html_path.name)
    if match is None:
        raise ValueError("Slide file name must use slide_XX.html")
    page_number = int(match.group(1))
    if not 1 <= page_number <= expected_pages:
        raise ValueError(f"Slide number must be between 1 and {expected_pages}")
    return html_path, page_number


@mcp.tool()
async def inspect_slide(
    html_file: str,
    expected_pages: int,
) -> list[TextContent | ImageContent]:
    """Validate one HTML slide, render its preview, and return visual feedback."""

    html_path, _ = validate_slide_path(html_file, expected_pages)
    # 当前幻灯片是被
    state = load_inspection_state()
    previous = state.get(html_path.name, {})
    attempt = int(previous.get("attempts", 0)) + 1
    max_attempts = int(os.environ.get("MAX_SLIDE_REVISIONS", "3"))
    if attempt > max_attempts:
        raise RuntimeError(
            f"{html_path.name} exceeded the inspection limit of {max_attempts}"
        )

    try:
        aspect_ratio = os.environ.get("ASPECT_RATIO", "16:9")
        await convert_html_to_pptx(html_path, aspect_ratio=aspect_ratio)
        preview_dir = get_workspace() / "previews"
        preview_dir.mkdir(exist_ok=True)
        preview_path = preview_dir / f"{html_path.stem}.jpg"
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "slide.pdf"
            async with PlaywrightConverter() as converter:
                image_dir = await converter.convert_to_pdf(
                    [html_path], pdf_path, aspect_ratio
                )
            shutil.copy2(image_dir / "slide_01.jpg", preview_path)

        result = {
            "status": "passed",
            "html": relative_path(html_path),
            "preview": relative_path(preview_path),
            "attempt": attempt,
        }
        state[html_path.name] = {
            "status": "passed",
            "attempts": attempt,
            "sha256": slide_digest(html_path),
            "preview": result["preview"],
            "last_error": None,
        }
        save_inspection_state(state)
        content: list[TextContent | ImageContent] = [
            TextContent(type="text", text=json.dumps(result, ensure_ascii=False))
        ]
        if os.environ.get("ENABLE_VISUAL_REVIEW", "false").lower() == "true":
            content.append(
                ImageContent(
                    type="image",
                    data=base64.b64encode(preview_path.read_bytes()).decode("ascii"),
                    mimeType="image/jpeg",
                )
            )
        return content
    except Exception as error:
        state[html_path.name] = {
            "status": "failed",
            "attempts": attempt,
            "sha256": None,
            "preview": None,
            "last_error": str(error)[:2000],
        }
        save_inspection_state(state)
        raise RuntimeError(f"Slide inspection failed: {error}") from error


def validate_slides_directory(slides_dir: Path, expected_pages: int) -> None:
    """Require a complete, freshly inspected HTML slide set."""
    if relative_path(slides_dir) != "slides":
        raise ValueError("Design outcome must be the slides directory")
    if not 2 <= expected_pages <= 20:
        raise ValueError("expected_pages must be between 2 and 20")
    css_path = slides_dir / "global.css"
    if not css_path.is_file() or css_path.stat().st_size == 0:
        raise FileNotFoundError("slides/global.css does not exist or is empty")

    expected_names = [
        f"slide_{index:02d}.html" for index in range(1, expected_pages + 1)
    ]
    actual_names = sorted(path.name for path in slides_dir.glob("*.html"))
    if actual_names != expected_names:
        raise ValueError(
            f"Expected slide files {expected_names}, but found {actual_names}"
        )

    state = load_inspection_state()
    for name in expected_names:
        html_path = slides_dir / name
        record = state.get(name)
        if record is None or record.get("status") != "passed":
            raise ValueError(f"{name} has not passed inspect_slide")
        if record.get("sha256") != slide_digest(html_path):
            raise ValueError(f"{name} changed after inspect_slide; inspect it again")


@mcp.tool()
def finalize(outcome: str, expected_pages: int | None = None) -> str:
    """Finish a stage after validating its file or inspected slide directory."""
    path = resolve_workspace_path(outcome)
    if path.is_dir():
        if expected_pages is None:
            raise ValueError("Design finalize requires expected_pages")
        validate_slides_directory(path, expected_pages)
    elif path.is_file():
        if path.stat().st_size == 0:
            raise ValueError(f"Outcome file is empty: {outcome}")
    else:
        raise FileNotFoundError(f"Outcome does not exist: {outcome}")
    return relative_path(path)


if __name__ == "__main__":
    install_if_needed()
    mcp.run(transport="stdio", show_banner=False)
