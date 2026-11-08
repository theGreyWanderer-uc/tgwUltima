"""U7 catalogue names and retained Exult frame/quality naming rules.

TEXT.FLX shapes, messages and misc strings have separate namespaces.
text_names.load_u7_text_names implements selected-source replacement;
explicit sparse inspection overlay APIs remain available here.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Sequence

from titan.u7.flex import U7FlexArchive
from titan.u7.text import (
    SIVariant,
    TextEncoding,
    U7TextBanks,
    U7TextMessages,
    decode_text_source,
)

__all__ = [
    "U7ShapeNames",
    "U7FrameNames",
    "U7FrameNameRule",
    "U7NameResolution",
    "format_u7_name",
]


def format_u7_name(raw: str, quantity: int = 1, *, bare: bool = False) -> str:
    """Format prefix/stem/singular/plural fields; bare labels retain singular endings."""
    if "/" not in raw:
        return raw if bare or quantity <= 1 else f"{quantity} {raw}"
    parts = raw.split("/", 3)
    if len(parts) != 4:
        return "?"
    prefix, stem, singular, plural = parts
    if bare:
        return stem + singular
    if quantity <= 1:
        return (prefix + " " if prefix else "") + stem + singular
    return f"{quantity} {stem}{plural}"


def _clean_article_name(raw: str) -> str:
    """Return a bare singular catalogue label, without discarding the singular suffix."""
    return format_u7_name(raw, bare=True)


class U7ShapeNames:
    """Shape-only names with retained raw morphology and optional full text banks."""

    def __init__(
        self,
        names: Sequence[str],
        *,
        banks: U7TextBanks | None = None,
        warnings: Sequence[str] = (),
    ) -> None:
        self.raw_names = tuple(names)
        self._names = [_clean_article_name(name) for name in names]
        self.text_banks = banks
        self.warnings = list(warnings)
        self.warnings.extend(
            f"Shape name {index} has malformed slash syntax."
            for index, name in enumerate(names)
            if "/" in name and len(name.split("/", 3)) != 4
        )

    @classmethod
    def from_file(
        cls, path: str, *, game: str = "bg", si_variant: SIVariant = "unmapped"
    ) -> U7ShapeNames:
        banks = U7TextBanks.from_file(path, game=game, si_variant=si_variant)
        return cls(banks.shapes, banks=banks, warnings=banks.warnings)

    @classmethod
    def from_static_dir(
        cls, static_dir: str, *, game: str = "bg"
    ) -> U7ShapeNames | None:
        textmsg = _text_file(Path(static_dir), "textmsg.txt")
        if textmsg is not None:
            return cls.from_textmsg(str(textmsg), mode="replace")
        path = _text_file(Path(static_dir), "text.flx")
        return cls.from_file(str(path), game=game) if path else None

    @classmethod
    def from_textmsg(
        cls,
        textmsg_path: str,
        base: U7ShapeNames | None = None,
        *,
        mode: Literal["overlay", "replace"] = "overlay",
        encoding: TextEncoding = "auto",
    ) -> U7ShapeNames:
        """Apply an explicit sparse inspection overlay, or select a replacement shape bank."""
        if mode not in ("overlay", "replace"):
            raise ValueError(f"Unknown shape-name loading mode: {mode}")
        text = U7TextMessages.from_file(textmsg_path, encoding=encoding)
        previous = base.raw_names if base is not None and mode == "overlay" else ()
        return cls(text.strings("shapes", previous), warnings=text.warnings)

    @classmethod
    def from_mod_dir(
        cls,
        mod_data_dir: str,
        base: U7ShapeNames | None = None,
        *,
        mode: Literal["overlay", "replace"] = "overlay",
        encoding: TextEncoding = "auto",
    ) -> U7ShapeNames | None:
        """Load a mod's explicit inspection overlay; engine selection uses text_names."""
        path = _text_file(Path(mod_data_dir), "textmsg.txt")
        return (
            cls.from_textmsg(str(path), base, mode=mode, encoding=encoding)
            if path
            else base
        )

    def raw_get(self, shape_num: int) -> str:
        """Return raw stored morphology, or empty text for an unknown shape."""
        return self.raw_names[shape_num] if 0 <= shape_num < len(self.raw_names) else ""

    def get(self, shape_num: int) -> str:
        """Return a bare singular label only from the shape namespace."""
        return self._names[shape_num] if 0 <= shape_num < len(self._names) else ""

    def display_name(self, shape_num: int, quantity: int = 1) -> str:
        """Apply stored article/plural rules using the caller's effective quantity."""
        return format_u7_name(self.raw_get(shape_num), quantity)

    def label(self, shape_num: int) -> str:
        name = self.get(shape_num)
        return f"{shape_num} ({name})" if name else str(shape_num)

    def find_shapes(self, pattern: str) -> list[int]:
        lower = pattern.casefold()
        return [
            index for index, name in enumerate(self._names) if lower in name.casefold()
        ]

    def __len__(self) -> int:
        return len(self._names)


@dataclass(frozen=True)
class U7FrameNameRule:
    """A stored frame/quality rule keeps actions and message references until resolution."""

    shape: int
    frame: int
    quality: int
    type: int
    msgid: int = 0
    othermsg: int = -255
    literal: str | None = None
    source: str = ""
    supplied_fields: int = 6


@dataclass(frozen=True)
class U7NameResolution:
    """Distinguish displayed text, explicit emptiness, suppression and missing runtime context."""

    kind: Literal["name", "empty", "suppressed", "default", "unresolved"]
    text: str
    rule: U7FrameNameRule | None = None
    reason: str = ""


def _text_file(directory: Path, filename: str) -> Path | None:
    direct = directory / filename
    if direct.is_file():
        return direct
    if directory.is_dir():
        return next(
            (
                path
                for path in directory.iterdir()
                if path.is_file() and path.name.lower() == filename.lower()
            ),
            None,
        )
    return None


class U7FrameNames:
    """Resolve retained frame/quality rules over current misc strings, not cached labels."""

    _FLX_RECORD_BG = 7
    _FLX_RECORD_SI = 4

    def __init__(
        self,
        lookup: dict[tuple[int, int], str] | None = None,
        *,
        rules: Sequence[U7FrameNameRule] = (),
        misc_names: Sequence[str] = (),
        game: str = "bg",
        si_variant: SIVariant = "unmapped",
        warnings: Sequence[str] = (),
    ) -> None:
        self.rules = {(r.shape, r.frame, r.quality): r for r in rules}
        for (shape, frame), value in (lookup or {}).items():
            self.rules[(shape, frame, -1)] = U7FrameNameRule(
                shape, frame, -1, 0, literal=value
            )
        self.misc_names = tuple(misc_names)
        self.game = game
        self.si_variant = si_variant
        self.warnings = list(warnings)

    @staticmethod
    def _clean_misc_name(raw: str) -> str:
        return _clean_article_name(raw)

    @classmethod
    def _load_misc_names(
        cls, text_flx_path: str, *, game: str = "bg", si_variant: SIVariant = "unmapped"
    ) -> list[str]:
        return list(
            U7TextBanks.from_file(text_flx_path, game=game, si_variant=si_variant).misc
        )

    @classmethod
    def from_text(
        cls,
        text: str,
        misc_names: Sequence[str],
        *,
        game: str = "bg",
        source: str = "",
        si_variant: SIVariant = "unmapped",
    ) -> U7FrameNames:
        """Read shape_info decimal fields, retaining quality, actions and source defaults."""
        parsed = U7TextMessages.from_bytes(text.encode("utf-8"))
        rules = []
        warnings = list(parsed.warnings)
        for _, value in sorted(parsed.sections.get("framenames", {}).items()):
            parts = value.split("/")

            def number(index: int, default: int = 0) -> int:
                if index >= len(parts):
                    return default
                try:
                    return int(parts[index], 10)
                except ValueError as error:
                    raise ValueError(
                        f"Invalid framenames numeric field: {value!r}"
                    ) from error

            shape = number(0, -1)
            if not 0 <= shape <= 0xFFFF:
                raise ValueError(f"Invalid framenames shape: {shape}")
            frame, quality, kind = number(1), number(2), number(3)
            rules.append(
                U7FrameNameRule(
                    shape,
                    -1 if frame < 0 else frame & 255,
                    -1 if quality < 0 else quality & 255,
                    kind,
                    number(4) if kind >= 0 else 0,
                    number(5, -255) if kind >= 0 else -255,
                    source=source,
                    supplied_fields=len(parts),
                )
            )
        return cls(
            rules=rules,
            misc_names=misc_names,
            game=game,
            si_variant=si_variant,
            warnings=warnings,
        )

    @classmethod
    def _parse_framenames(
        cls, lines: list[str], misc_names: list[str]
    ) -> dict[tuple[int, int], str]:
        """Compatibility preview of context-free rules; full rules live in from_text."""
        parsed = cls.from_text("\n".join(lines), misc_names)
        return {
            (r.shape, r.frame): parsed.get(r.shape, r.frame)
            for r in parsed.rules.values()
            if r.quality == -1 and r.type in (0, -1)
        }

    @classmethod
    def _load_misc_names_from_textmsg(
        cls,
        textmsg_path: str,
        base: list[str] | None = None,
        *,
        encoding: TextEncoding = "auto",
    ) -> list[str]:
        return U7TextMessages.from_file(textmsg_path, encoding=encoding).strings(
            "miscnames", base or ()
        )

    def with_misc(self, values: Sequence[str]) -> U7FrameNames:
        """Rebind inherited message references without changing their frame/quality rules."""
        return U7FrameNames(
            rules=list(self.rules.values()),
            misc_names=values,
            game=self.game,
            si_variant=self.si_variant,
            warnings=self.warnings,
        )

    def merged_with(self, other: U7FrameNames) -> U7FrameNames:
        merged = dict(self.rules)
        merged.update(other.rules)
        return U7FrameNames(
            rules=list(merged.values()),
            misc_names=other.misc_names,
            game=self.game,
            si_variant=self.si_variant,
            warnings=[*self.warnings, *other.warnings],
        )

    @classmethod
    def from_mod_dir(
        cls,
        mod_data_dir: str,
        text_flx_path: str | None,
        base: U7FrameNames | None = None,
        *,
        game: str | None = None,
        si_variant: SIVariant = "unmapped",
        encoding: TextEncoding = "auto",
    ) -> U7FrameNames | None:
        """Sparse inspection overlay, rebinding inherited rules even for misc-only changes."""
        directory = Path(mod_data_dir)
        textmsg, shape_info = (
            _text_file(directory, "textmsg.txt"),
            _text_file(directory, "shape_info.txt"),
        )
        if textmsg is None and shape_info is None:
            return base
        chosen_game = game or (base.game if base is not None else "bg")
        variant = base.si_variant if base is not None else si_variant
        misc = (
            list(base.misc_names)
            if base is not None
            else cls._load_misc_names(
                text_flx_path, game=chosen_game, si_variant=variant
            )
            if text_flx_path
            else []
        )
        warnings = []
        if textmsg is not None:
            parsed = U7TextMessages.from_file(textmsg, encoding=encoding)
            misc = parsed.strings("miscnames", misc)
            warnings.extend(parsed.warnings)
            if (
                base is not None
                and any(r.literal is not None for r in base.rules.values())
                and "miscnames" in parsed.sections
            ):
                warnings.append(
                    "Literal frame labels have no message references to rebind."
                )
        result = (
            base.with_misc(misc)
            if base is not None
            else cls(misc_names=misc, game=chosen_game, si_variant=variant)
        )
        result.warnings.extend(warnings)
        if shape_info is not None:
            text, _ = decode_text_source(shape_info.read_bytes(), encoding)
            result = result.merged_with(
                cls.from_text(
                    text,
                    misc,
                    game=chosen_game,
                    source=str(shape_info),
                    si_variant=variant,
                )
            )
        return result

    @classmethod
    def from_files(
        cls,
        shape_info_path: str,
        text_flx_path: str,
        *,
        game: str = "bg",
        si_variant: SIVariant = "unmapped",
        encoding: TextEncoding = "auto",
    ) -> U7FrameNames:
        text, _ = decode_text_source(Path(shape_info_path).read_bytes(), encoding)
        return cls.from_text(
            text,
            cls._load_misc_names(text_flx_path, game=game, si_variant=si_variant),
            game=game,
            source=shape_info_path,
            si_variant=si_variant,
        )

    @classmethod
    def from_flx(
        cls,
        exult_flx_path: str,
        text_flx_path: str,
        game: str = "bg",
        *,
        si_variant: SIVariant = "unmapped",
    ) -> U7FrameNames:
        data = U7FlexArchive.from_file(exult_flx_path, strict=True).get_record(
            cls._FLX_RECORD_BG if game.lower() == "bg" else cls._FLX_RECORD_SI
        )
        if not data:
            raise ValueError(f"Empty shape_info resource in {exult_flx_path}")
        return cls.from_text(
            data.decode("latin-1"),
            cls._load_misc_names(text_flx_path, game=game, si_variant=si_variant),
            game=game,
            source=exult_flx_path,
            si_variant=si_variant,
        )

    @classmethod
    def from_static_and_exult(
        cls,
        static_dir: str,
        exult_data_dir: str,
        game: str = "bg",
        *,
        si_variant: SIVariant = "unmapped",
    ) -> U7FrameNames | None:
        text = _text_file(Path(static_dir), "text.flx")
        if text is None:
            return None
        root = Path(exult_data_dir)
        for directory in (root, root / "data"):
            resource = _text_file(directory, f"exult_{game}.flx")
            if resource:
                return cls.from_flx(
                    str(resource), str(text), game, si_variant=si_variant
                )
        source = root / game / "shape_info.txt"
        return (
            cls.from_files(str(source), str(text), game=game, si_variant=si_variant)
            if source.is_file()
            else None
        )

    def rule_for(
        self, shape: int, frame: int, quality: int = -1
    ) -> U7FrameNameRule | None:
        """Prefer exact frame/quality, frame wildcard-quality, quality wildcard-frame, then both."""
        for key in dict.fromkeys(
            (
                (shape, frame, quality),
                (shape, frame, -1),
                (shape, -1, quality),
                (shape, -1, -1),
            )
        ):
            if key in self.rules:
                return self.rules[key]
        return None

    def resolve(
        self,
        shape: int,
        frame: int,
        shape_names: U7ShapeNames | None = None,
        *,
        quality: int = -1,
        has_quality: bool | None = None,
        is_body: bool = False,
        npc_name: str | None = None,
        quantity: int | None = None,
    ) -> U7NameResolution:
        """Resolve static actions; NPC eligibility/name must come from explicit runtime context.

        quality is the caller's effective binding quality (-1 for NPC/non-quality
        objects). npc_name=None means unavailable context; an empty name means a
        known ineligible/unnamed NPC and selects the stored default instead.
        """
        rule = self.rule_for(shape, frame, quality)
        shape_raw = shape_names.raw_get(shape) if shape_names is not None else ""

        def display(raw: str) -> str:
            return format_u7_name(
                raw, 1 if quantity is None else quantity, bare=quantity is None
            )

        def default() -> U7NameResolution:
            return U7NameResolution("default", display(shape_raw), rule)

        if rule is None or rule.type == -255:
            return default()
        if rule.type < 0:
            return U7NameResolution("suppressed", "", rule)
        if rule.literal is not None:
            value = display(rule.literal)
            return U7NameResolution("name" if value else "empty", value, rule)
        if not 0 <= rule.msgid < len(self.misc_names):
            return default()
        msg = self.misc_names[rule.msgid]
        if rule.type == 0:
            value = display(msg)
            return U7NameResolution("name" if value else "empty", value, rule)
        if has_quality is False and not is_body:
            return default()
        if has_quality is None and not is_body:
            return U7NameResolution(
                "unresolved", "", rule, "Item class/quality context is required."
            )
        if rule.type < 3:
            other = (
                self.misc_names[rule.othermsg]
                if 0 <= rule.othermsg < len(self.misc_names)
                else shape_raw
            )
        else:
            if npc_name is None:
                return U7NameResolution(
                    "unresolved",
                    "",
                    rule,
                    "Eligible NPC/body name context is required.",
                )
            if not npc_name:
                if 0 <= rule.othermsg < len(self.misc_names):
                    value = display(self.misc_names[rule.othermsg])
                    return U7NameResolution("name" if value else "empty", value, rule)
                return (
                    U7NameResolution("suppressed", "", rule)
                    if rule.othermsg < 0 and rule.othermsg != -255
                    else default()
                )
            other = npc_name
        value = other + msg if rule.type & 1 else msg + other
        return U7NameResolution("name" if value else "empty", value, rule)

    def get(self, shape: int, frame: int, quality: int = -1) -> str:
        """Return a context-free bare label, preserving explicit suppression/empty results."""
        return self.resolve(shape, frame, quality=quality).text

    def label(
        self,
        shape: int,
        frame: int,
        shape_names: U7ShapeNames | None = None,
        *,
        quality: int = -1,
        has_quality: bool | None = None,
        is_body: bool = False,
        npc_name: str | None = None,
    ) -> str:
        """Return a bare label; only default actions fall back to the shape name."""
        return self.resolve(
            shape,
            frame,
            shape_names,
            quality=quality,
            has_quality=has_quality,
            is_body=is_body,
            npc_name=npc_name,
        ).text
