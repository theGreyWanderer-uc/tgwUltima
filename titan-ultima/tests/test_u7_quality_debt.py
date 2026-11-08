"""Missing pixels and font fallback at rendering/export boundaries."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw, ImageFont

from titan.u7.cli import cmd_palette_export, cmd_shape_animate
from titan.u7.map import _frame_to_rgba, _load_map_font
from titan.u7.shape import U7Shape


def test_map_frame_without_pixels_has_a_clear_error() -> None:
    with pytest.raises(ValueError, match="U7 frame has no pixel data"):
        _frame_to_rgba(U7Shape.Frame(), bytes(768))


def test_cycle_export_rejects_empty_frame_without_creating_gif(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "empty.shp"
    source.write_bytes(b"placeholder")
    shape = U7Shape()
    shape.frames = [U7Shape.Frame()]
    monkeypatch.setattr(U7Shape, "from_file", lambda _path: shape)
    output = tmp_path / "empty.gif"
    status = cmd_shape_animate(
        SimpleNamespace(
            file=str(source),
            palette=None,
            frame=0,
            static=None,
            shape=None,
            mode="cycle",
            output=str(output),
        )
    )
    assert status == 1
    assert "Frame 0 has no pixel data" in capsys.readouterr().err
    assert not output.exists()


def test_map_font_fallback_can_draw_when_arial_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fallback = ImageFont.load_default()

    def missing_font(*args, **kwargs):
        raise OSError("Arial unavailable")

    monkeypatch.setattr(ImageFont, "truetype", missing_font)
    monkeypatch.setattr(ImageFont, "load_default", lambda: fallback)
    font = _load_map_font(18)
    image = Image.new("L", (100, 30))
    ImageDraw.Draw(image).text((0, 0), "SC 0", fill=255, font=font)
    assert image.getbbox() is not None


@pytest.mark.parametrize(
    "encoding,component", [("auto", 64), ("6bit", 64), ("8bit", 16)]
)
def test_palette_export_keeps_requested_component_encoding(
    tmp_path: Path,
    encoding: str,
    component: int,
) -> None:
    source = tmp_path / "palette.pal"
    source.write_bytes(bytes([16]) * 768)
    output = tmp_path / "export"
    status = cmd_palette_export(
        SimpleNamespace(
            file=str(source),
            output=str(output),
            index=None,
            encoding=encoding,
        )
    )
    assert status == 0
    with Image.open(output / "palette_swatch.png") as image:
        assert image.convert("RGB").getpixel((0, 0)) == (component,) * 3


def test_palette_export_reports_invalid_encoding(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "palette.pal"
    source.write_bytes(bytes(768))
    output = tmp_path / "export"
    status = cmd_palette_export(
        SimpleNamespace(
            file=str(source),
            output=str(output),
            index=None,
            encoding="9bit",
        )
    )
    assert status == 1
    assert "Unknown encoding '9bit'" in capsys.readouterr().err
    assert not list(output.iterdir())
