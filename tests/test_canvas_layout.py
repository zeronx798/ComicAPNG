"""Tests for fixed transparent canvas layout."""

from __future__ import annotations

from PIL import Image

from comicapng.core.image_layout import calculate_canvas, calculate_fit, render_to_canvas


def test_same_sized_pages_use_same_canvas() -> None:
    assert calculate_canvas([(120, 180), (120, 180)]) == (120, 180)
    assert calculate_fit((120, 180), (120, 180)).render_width == 120


def test_portrait_and_landscape_use_largest_dimensions() -> None:
    assert calculate_canvas([(100, 200), (300, 80)]) == (300, 200)


def test_smaller_page_is_enlarged_proportionally() -> None:
    layout = calculate_fit((20, 40), (100, 100))
    assert (layout.render_width, layout.render_height) == (50, 100)
    assert (layout.offset_x, layout.offset_y) == (25, 0)
    assert layout.render_width / layout.render_height == 0.5


def test_render_preserves_aspect_ratio_and_transparent_padding() -> None:
    source = Image.new("RGBA", (2, 4), (220, 30, 40, 255))
    rendered, layout = render_to_canvas(source, (8, 8))
    try:
        assert rendered.size == (8, 8)
        assert (layout.render_width, layout.render_height) == (4, 8)
        assert rendered.getpixel((0, 4))[3] == 0
        assert rendered.getpixel((7, 4))[3] == 0
        assert rendered.getpixel((3, 4))[3] == 255
    finally:
        rendered.close()
        source.close()


def test_fit_never_stretches_or_crops() -> None:
    layout = calculate_fit((17, 31), (100, 80))
    source_ratio = 17 / 31
    rendered_ratio = layout.render_width / layout.render_height
    assert abs(source_ratio - rendered_ratio) < 0.01
    assert layout.render_width <= 100
    assert layout.render_height <= 80
