"""UW1 floor, ceiling, and wall texture archives and batch export."""

from __future__ import annotations

import csv
import json
import re
import struct
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from titan.uw1.palette import UW1Palette
from titan.uw2.strings import GameStrings

_TEXTURE_ARCHIVE_NAME = re.compile(r"^(?P<kind>[FW])(?P<size>\d+)\.TR$", re.I)
_TEXTURE_STRING_BLOCK = 10
_FLOOR_STRING_ORIGIN = 510


class UW1TextureError(ValueError):
    """Raised when UW1 texture data is missing or malformed."""


@dataclass(frozen=True)
class UW1Texture:
    """One indexed-colour texture from a UW1 ``.TR`` archive."""

    index: int
    offset: int
    resolution: int
    pixels: bytes

    def to_image(self, palette: UW1Palette) -> Image.Image:
        """Convert this texture to an opaque RGBA image."""
        array = np.frombuffer(self.pixels, dtype=np.uint8).reshape(
            (self.resolution, self.resolution)
        )
        image = Image.fromarray(array, mode="P")
        image.putpalette(palette.flattened_rgb())
        return image.convert("RGBA")


@dataclass(frozen=True)
class UW1TextureArchive:
    """A parsed UW1 ``F*.TR`` or ``W*.TR`` texture archive."""

    path: Path
    resolution: int
    textures: tuple[UW1Texture, ...]

    @classmethod
    def from_data(
        cls, data: bytes, *, path: str | Path = "<memory>"
    ) -> UW1TextureArchive:
        """Parse and validate one complete texture archive."""
        archive_path = Path(path)
        if len(data) < 4:
            raise UW1TextureError(f"{archive_path} is too small for a TR header")
        format_byte, resolution, texture_count = struct.unpack_from("<BBH", data)
        if format_byte != 2:
            raise UW1TextureError(
                f"{archive_path} has TR format byte {format_byte:#x}; expected 0x2"
            )
        if resolution < 1:
            raise UW1TextureError(f"{archive_path} has zero texture resolution")
        table_end = 4 + texture_count * 4
        if table_end > len(data):
            raise UW1TextureError(f"{archive_path} offset table extends past EOF")

        texture_size = resolution * resolution
        offsets = struct.unpack_from(f"<{texture_count}I", data, 4)
        textures: list[UW1Texture] = []
        for index, offset in enumerate(offsets):
            end = offset + texture_size
            if offset < table_end or end > len(data):
                raise UW1TextureError(
                    f"{archive_path} texture {index} range {offset:#x}..{end:#x} "
                    f"is outside its {len(data):#x}-byte archive"
                )
            textures.append(
                UW1Texture(
                    index=index,
                    offset=offset,
                    resolution=resolution,
                    pixels=data[offset:end],
                )
            )
        return cls(
            path=archive_path,
            resolution=resolution,
            textures=tuple(textures),
        )

    @classmethod
    def from_file(cls, path: str | Path) -> UW1TextureArchive:
        """Read and parse a texture archive from disk."""
        archive_path = Path(path)
        return cls.from_data(archive_path.read_bytes(), path=archive_path)

    def summary(self) -> dict[str, object]:
        """Return JSON-serializable archive metadata."""
        return {
            "archive": self.path.name,
            "resolution": self.resolution,
            "texture_count": len(self.textures),
            "textures": [
                {
                    "texture_id": texture.index,
                    "offset": texture.offset,
                    "resolution": texture.resolution,
                }
                for texture in self.textures
            ],
        }


@dataclass(frozen=True)
class UW1TextureExportRecord:
    """One row in the texture export manifests."""

    archive: str
    texture_kind: str
    texture_id: int
    description: str
    resolution: int
    offset: int
    png: str


def data_directory(game_directory: str | Path) -> Path:
    """Resolve an install root or its ``DATA`` directory."""
    path = Path(game_directory).expanduser()
    return path if path.name.upper() == "DATA" else path / "DATA"


def discover_texture_archives(game_directory: str | Path) -> list[Path]:
    """Find all UW1 ``.TR`` texture archives in deterministic order."""
    directory = data_directory(game_directory)
    if not directory.is_dir():
        raise UW1TextureError(f"UW1 DATA directory not found: {directory}")
    archives = sorted(
        (path for path in directory.iterdir() if path.suffix.upper() == ".TR"),
        key=lambda path: path.name.upper(),
    )
    if not archives:
        raise UW1TextureError(f"no UW1 .TR texture archives found in {directory}")
    return archives


def inspect_texture_archives(game_directory: str | Path) -> list[dict[str, object]]:
    """Parse every discovered texture archive and return summaries."""
    return [
        UW1TextureArchive.from_file(path).summary()
        for path in discover_texture_archives(game_directory)
    ]


def export_all_textures(
    game_directory: str | Path,
    output: str | Path,
    *,
    scale: int = 1,
    contact_sheets: bool = False,
) -> dict[str, object]:
    """Export every UW1 floor/wall texture and write CSV/JSON manifests."""
    if scale < 1:
        raise UW1TextureError(f"texture scale must be at least 1: {scale}")

    directory = data_directory(game_directory)
    palette_path = directory / "PALS.DAT"
    if not palette_path.is_file():
        raise UW1TextureError(f"UW1 palette not found: {palette_path}")
    palette = UW1Palette.from_file(palette_path, index=0)
    descriptions = _load_texture_descriptions(directory / "STRINGS.PAK")

    output_path = Path(output).expanduser()
    textures_root = output_path / "textures"
    textures_root.mkdir(parents=True, exist_ok=True)
    records: list[UW1TextureExportRecord] = []
    archives_summary: list[dict[str, object]] = []

    for archive_path in discover_texture_archives(directory):
        archive = UW1TextureArchive.from_file(archive_path)
        kind, expected_resolution = _archive_identity(archive_path)
        if (
            expected_resolution is not None
            and archive.resolution != expected_resolution
        ):
            raise UW1TextureError(
                f"{archive_path.name} declares {archive.resolution}x{archive.resolution}; "
                f"its name says {expected_resolution}x{expected_resolution}"
            )

        archive_stem = archive_path.stem.lower()
        archive_output = textures_root / archive_stem
        archive_output.mkdir(parents=True, exist_ok=True)
        rendered: list[Image.Image] = []
        for texture in archive.textures:
            image = texture.to_image(palette)
            if scale != 1:
                image = image.resize(
                    (image.width * scale, image.height * scale),
                    Image.Resampling.NEAREST,
                )
            png_path = archive_output / f"{archive_stem}_{texture.index:03d}.png"
            image.save(png_path)
            rendered.append(image)
            records.append(
                UW1TextureExportRecord(
                    archive=archive_path.name,
                    texture_kind=kind,
                    texture_id=texture.index,
                    description=_texture_description(
                        descriptions, kind=kind, texture_id=texture.index
                    ),
                    resolution=archive.resolution,
                    offset=texture.offset,
                    png=png_path.relative_to(output_path).as_posix(),
                )
            )

        contact_sheet_path: str | None = None
        if contact_sheets:
            sheet_path = archive_output / f"{archive_stem}_contact_sheet.png"
            _make_contact_sheet(rendered).save(sheet_path)
            contact_sheet_path = sheet_path.relative_to(output_path).as_posix()
        archives_summary.append(
            {
                "archive": archive_path.name,
                "texture_kind": kind,
                "resolution": archive.resolution,
                "texture_count": len(archive.textures),
                "contact_sheet": contact_sheet_path,
            }
        )

    _write_csv(output_path / "textures_manifest.csv", records)
    result: dict[str, object] = {
        "format": "ultima-underworld-1-texture-export",
        "palette_index": 0,
        "scale": scale,
        "archive_count": len(archives_summary),
        "texture_count": len(records),
        "archives": archives_summary,
        "manifest_csv": "textures_manifest.csv",
    }
    (output_path / "textures_manifest.json").write_text(
        json.dumps(
            {**result, "textures": [asdict(record) for record in records]}, indent=2
        )
        + "\n",
        encoding="utf-8",
    )
    return result


def _archive_identity(path: Path) -> tuple[str, int | None]:
    match = _TEXTURE_ARCHIVE_NAME.match(path.name)
    if match is None:
        return "unknown", None
    kind = "floor" if match.group("kind").upper() == "F" else "wall"
    return kind, int(match.group("size"))


def _load_texture_descriptions(path: Path) -> list[str] | None:
    if not path.is_file():
        return None
    try:
        return GameStrings.from_file(path).blocks.get(_TEXTURE_STRING_BLOCK)
    except (IndexError, OSError, struct.error, ValueError):
        return None


def _texture_description(
    descriptions: list[str] | None, *, kind: str, texture_id: int
) -> str:
    if descriptions is None:
        return ""
    string_index = texture_id if kind == "wall" else _FLOOR_STRING_ORIGIN - texture_id
    if string_index < 0 or string_index >= len(descriptions):
        return ""
    return descriptions[string_index]


def _make_contact_sheet(images: list[Image.Image], columns: int = 16) -> Image.Image:
    if not images:
        raise UW1TextureError("cannot make a contact sheet without textures")
    width, height = images[0].size
    rows = (len(images) + columns - 1) // columns
    sheet = Image.new("RGBA", (columns * width, rows * height), (0, 0, 0, 255))
    for index, image in enumerate(images):
        sheet.alpha_composite(
            image, ((index % columns) * width, (index // columns) * height)
        )
    return sheet


def _write_csv(path: Path, records: list[UW1TextureExportRecord]) -> None:
    fieldnames = list(UW1TextureExportRecord.__dataclass_fields__)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(asdict(record) for record in records)
