"""Fixed-canvas image layout and rendering."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from math import floor

from PIL import Image


@dataclass(frozen=True, slots=True)
class PageLayout:
    source_width: int
    source_height: int
    render_width: int
    render_height: int
    offset_x: int
    offset_y: int


def calculate_canvas(sizes: Iterable[tuple[int, int]]) -> tuple[int, int]:
    checked = list(sizes)
    if not checked:
        raise ValueError("At least one page size is required")
    if any(width <= 0 or height <= 0 for width, height in checked):
        raise ValueError("Page dimensions must be positive")
    return max(width for width, _ in checked), max(height for _, height in checked)


def calculate_fit(source_size: tuple[int, int], canvas_size: tuple[int, int]) -> PageLayout:
    source_width, source_height = source_size
    canvas_width, canvas_height = canvas_size
    if min(source_width, source_height, canvas_width, canvas_height) <= 0:
        raise ValueError("Image and canvas dimensions must be positive")

    scale = min(canvas_width / source_width, canvas_height / source_height)
    render_width = max(1, min(canvas_width, floor(source_width * scale + 0.5)))
    render_height = max(1, min(canvas_height, floor(source_height * scale + 0.5)))
    offset_x = (canvas_width - render_width) // 2
    offset_y = (canvas_height - render_height) // 2
    return PageLayout(
        source_width=source_width,
        source_height=source_height,
        render_width=render_width,
        render_height=render_height,
        offset_x=offset_x,
        offset_y=offset_y,
    )


def render_to_canvas(
    image: Image.Image,
    canvas_size: tuple[int, int],
) -> tuple[Image.Image, PageLayout]:
    """Fit an image proportionally and center it on a transparent RGBA canvas."""
    source = image.convert("RGBA")
    layout = calculate_fit(source.size, canvas_size)
    if source.size != (layout.render_width, layout.render_height):
        source = source.resize(
            (layout.render_width, layout.render_height),
            Image.Resampling.LANCZOS,
        )
    canvas = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    canvas.alpha_composite(source, (layout.offset_x, layout.offset_y))
    return canvas, layout
