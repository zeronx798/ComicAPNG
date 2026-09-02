"""Deterministic varied image fixtures for page-reordering validation."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

RgbColor = tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class ReorderFixtureSpec:
    index: int
    size: tuple[int, int]
    start_color: RgbColor
    end_color: RgbColor
    probe_color: RgbColor

    @property
    def filename(self) -> str:
        return f"page-{self.index:02d}.png"

    @property
    def label(self) -> str:
        return f"PAGE {self.index:02d}"


REORDER_FIXTURE_SPECS = (
    ReorderFixtureSpec(1, (480, 720), (170, 28, 48), (255, 164, 58), (245, 35, 45)),
    ReorderFixtureSpec(2, (720, 480), (15, 91, 148), (42, 210, 190), (20, 110, 245)),
    ReorderFixtureSpec(3, (540, 840), (83, 28, 145), (222, 82, 180), (150, 45, 230)),
    ReorderFixtureSpec(4, (800, 450), (20, 125, 65), (180, 225, 45), (35, 205, 80)),
    ReorderFixtureSpec(5, (600, 600), (165, 78, 12), (250, 210, 45), (245, 135, 20)),
    ReorderFixtureSpec(6, (450, 800), (25, 44, 112), (85, 120, 240), (60, 75, 225)),
    ReorderFixtureSpec(7, (840, 540), (105, 20, 80), (240, 90, 105), (225, 35, 130)),
    ReorderFixtureSpec(8, (640, 960), (15, 115, 120), (80, 225, 185), (25, 190, 180)),
    ReorderFixtureSpec(9, (960, 640), (70, 75, 80), (205, 215, 225), (120, 130, 140)),
    ReorderFixtureSpec(10, (700, 900), (95, 45, 12), (225, 130, 45), (180, 85, 25)),
)


def _blend(start: RgbColor, end: RgbColor, numerator: int, denominator: int) -> RgbColor:
    return tuple(
        round(first + (second - first) * numerator / denominator)
        for first, second in zip(start, end, strict=True)
    )  # type: ignore[return-value]


def render_reorder_fixture(spec: ReorderFixtureSpec, destination: Path) -> Path:
    """Render one deterministic, visually distinctive RGBA page."""
    width, height = spec.size
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", spec.size, (*spec.start_color, 255))
    draw = ImageDraw.Draw(image, "RGBA")
    denominator = max(1, height - 1)
    for y in range(height):
        draw.line((0, y, width, y), fill=(*_blend(spec.start_color, spec.end_color, y, denominator), 255))

    unit = max(8, min(width, height) // 24)
    pattern = spec.index % 4
    if pattern == 0:
        for offset in range(-height, width, unit * 3):
            draw.polygon(
                (
                    (offset, 0),
                    (offset + unit, 0),
                    (offset + height + unit, height),
                    (offset + height, height),
                ),
                fill=(255, 255, 255, 58),
            )
    elif pattern == 1:
        for x in range(unit, width, unit * 3):
            draw.rectangle((x, 0, x + unit, height), fill=(255, 255, 255, 45))
    elif pattern == 2:
        for y in range(0, height, unit * 2):
            for x in range((y // (unit * 2)) % 2 * unit, width, unit * 2):
                draw.rectangle((x, y, x + unit, y + unit), fill=(15, 20, 30, 65))
    else:
        radius = unit
        for y in range(unit, height, unit * 4):
            for x in range(unit, width, unit * 4):
                draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=(255, 255, 255, 55))

    border = max(6, min(width, height) // 45)
    draw.rectangle(
        (border, border, width - border - 1, height - border - 1),
        outline=(255, 255, 255, 235),
        width=border,
    )
    inset = border * (2 + spec.index % 3)
    draw.rectangle(
        (inset, inset, width - inset - 1, height - inset - 1),
        outline=(10, 15, 25, 190),
        width=max(2, border // 2),
    )

    center_x, center_y = width // 2, height // 2
    probe_radius = max(18, min(width, height) // 12)
    draw.rectangle(
        (
            center_x - probe_radius,
            center_y - probe_radius,
            center_x + probe_radius,
            center_y + probe_radius,
        ),
        fill=(*spec.probe_color, 255),
        outline=(255, 255, 255, 255),
        width=max(3, border // 2),
    )

    font_size = max(36, min(width, height) // 8)
    font = ImageFont.load_default(size=font_size)
    text_box = draw.textbbox((0, 0), spec.label, font=font, stroke_width=max(2, border // 3))
    text_width = text_box[2] - text_box[0]
    text_height = text_box[3] - text_box[1]
    label_padding = max(12, border * 2)
    label_center_y = max(
        label_padding + text_height // 2,
        min(height // 4, height - label_padding - text_height // 2),
    )
    draw.rounded_rectangle(
        (
            center_x - text_width // 2 - label_padding,
            label_center_y - text_height // 2 - label_padding,
            center_x + text_width // 2 + label_padding,
            label_center_y + text_height // 2 + label_padding,
        ),
        radius=label_padding,
        fill=(5, 8, 15, 185),
        outline=(255, 255, 255, 220),
        width=max(2, border // 2),
    )
    draw.text(
        (center_x, label_center_y),
        spec.label,
        font=font,
        anchor="mm",
        fill=(255, 255, 255, 255),
        stroke_width=max(2, border // 3),
        stroke_fill=(0, 0, 0, 255),
    )

    try:
        image.save(destination, format="PNG", optimize=False, compress_level=6)
    finally:
        image.close()
    return destination.resolve()


def generate_reorder_fixtures(
    output_directory: Path,
    specs: Iterable[ReorderFixtureSpec] = REORDER_FIXTURE_SPECS,
) -> tuple[Path, ...]:
    """Generate a stable ordered fixture sequence in ``output_directory``."""
    output_directory = Path(output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)
    return tuple(
        render_reorder_fixture(spec, output_directory / spec.filename) for spec in specs
    )
