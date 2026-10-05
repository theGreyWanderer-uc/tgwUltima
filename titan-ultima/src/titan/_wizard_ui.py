"""Shared Questionary prompts, with a fallback for redirected terminal input."""

from __future__ import annotations

import re
import sys
from copy import copy
from typing import Any, Mapping


class PromptCancelled(Exception):
    pass


def menus_enabled() -> bool:
    return bool(sys.stdin.isatty() and sys.stdout.isatty())


def _label(prompt: str) -> str:
    return (
        re.sub(r"\[[^\[\]]*\]", "", prompt).strip().strip("> :\n") or "Choose an option"
    )


def _answer(prompt):
    result = prompt.ask()
    if result is None:
        raise PromptCancelled
    return result


def _choice_hotkeys(values: list[str]) -> dict[str, str]:
    """Single action keys; long IDs stay on arrow/search selection."""
    numeric = [value for value in values if value.isdecimal()]
    numeric_keys = all(len(value) == 1 for value in numeric)
    return {
        value: value
        for value in values
        if len(value) == 1
        and value.isascii()
        and value.isalnum()
        and (not value.isdecimal() or numeric_keys)
    }


def _select_hotkeys(options: list[Any]) -> dict[str, Any]:
    """Give direct selectors semantic keys, or numbers for a short owner list."""
    enabled = [
        item
        for item in options
        if not getattr(item, "disabled", False)
        and getattr(item, "value", None) is not None
    ]
    values = [item.value for item in enabled]
    numeric = [
        str(value)
        for value in values
        if isinstance(value, int) or isinstance(value, str) and value.isdecimal()
    ]
    numeric_keys = all(len(value) == 1 for value in numeric)
    candidates = [
        str(value).upper()
        if isinstance(value, int) and numeric_keys
        else value.upper()
        if isinstance(value, str) and value.isdecimal() and numeric_keys
        else value[:1].upper()
        if isinstance(value, str) and not value.isdecimal()
        else ""
        for value in values
    ]
    keys: dict[str, Any] = {}
    for item, key in zip(enabled, candidates):
        if (
            len(key) == 1
            and key.isascii()
            and key.isalnum()
            and candidates.count(key) == 1
        ):
            keys[key] = item.value
    if len(enabled) <= 9:
        for index, item in enumerate(enabled, 1):
            if (
                not isinstance(item.value, int)
                and not (isinstance(item.value, str) and item.value.isdecimal())
                and not any(item.value == value for value in keys.values())
            ):
                key = str(index)
                if key not in keys:
                    keys[key] = item.value
    return keys


def _hotkey_title(title: Any, key: str) -> Any:
    prefix = f"[{key}] "
    if isinstance(title, list):
        return (
            title
            if title and title[0][1].startswith(prefix)
            else [("", prefix), *title]
        )
    return (
        title
        if isinstance(title, str) and title.startswith(prefix)
        else f"{prefix}{title}"
    )


def select(
    prompt: str,
    *,
    q: Any = None,
    hotkeys: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> Any:
    """Keep a single-choice menu's highlight on its cursor, including defaults."""
    if q is None:
        import questionary as q
    from prompt_toolkit.styles import Style
    from prompt_toolkit.output import ColorDepth
    from questionary.prompts.common import InquirerControl

    if hotkeys is None:
        options = [
            q.Choice(item) if isinstance(item, str) else item
            for item in kwargs.get("choices", [])
        ]
        hotkeys = _select_hotkeys(options)
        kwargs["choices"] = options
    # Numeric IDs and internal tokens such as S150 are never key sequences.
    hotkeys = {
        key: value
        for key, value in hotkeys.items()
        if len(key) == 1 and key.isascii() and key.isalnum()
    }
    for item in kwargs.get("choices", []):
        key = next(
            (
                key
                for key, value in hotkeys.items()
                if getattr(item, "value", None) == value
            ),
            None,
        )
        if key:
            # Copy rather than changing Choice objects reused by another prompt.
            replacement = copy(item)
            replacement.title = _hotkey_title(item.title, key)
            options = list(kwargs["choices"])
            options[options.index(item)] = replacement
            kwargs["choices"] = options
    kwargs.setdefault("style", Style.from_dict({"highlighted": "bold reverse"}))
    kwargs.setdefault("color_depth", ColorDepth.TRUE_COLOR)
    if hotkeys:
        kwargs.setdefault("use_jk_keys", False)
        kwargs.setdefault(
            "instruction", f"(Hotkeys: {'/'.join(hotkeys)}; arrows + Enter)"
        )
    question = q.select(prompt, **kwargs)
    application = getattr(question, "application", None)
    if application is not None:
        for control in application.layout.find_all_controls():
            if isinstance(control, InquirerControl):
                # Questionary marks `default` as selected as well as positioning
                # the cursor. Single-choice menus only need the cursor highlight.
                control.selected_options.clear()
                if hotkeys:
                    from prompt_toolkit.key_binding import (
                        KeyBindings,
                        merge_key_bindings,
                    )

                    bindings = KeyBindings()
                    for key, value in hotkeys.items():
                        index = next(
                            i
                            for i, item in enumerate(control.choices)
                            if item.value == value
                        )

                        def finish(event, index=index, value=value, control=control):
                            control.pointed_at = index
                            control.is_answered = True
                            event.app.exit(result=value)

                        for variant in dict.fromkeys((key.lower(), key.upper())):
                            bindings.add(variant, eager=True)(finish)
                    original = application.key_bindings
                    application.key_bindings = merge_key_bindings(
                        [original, bindings] if original is not None else [bindings]
                    )
                if any(isinstance(choice.title, list) for choice in control.choices):
                    # Questionary renders formatted choice titles verbatim.
                    # Highlight their name fragment while retaining swatch colours.
                    def highlighted_tokens(control=control):
                        focused = False
                        fragments = []
                        for style, value, *extra in control._get_choice_tokens():
                            if style == "[SetCursorPosition]":
                                focused = True
                            if "class:choice-label" in style:
                                style += (
                                    " class:highlighted" if focused else " class:text"
                                )
                            fragments.append((style, value, *extra))
                            if "\n" in value:
                                focused = False
                        return fragments

                    control.text = highlighted_tokens
    return question


def path_prompt(prompt: str, default: str = "", *, q: Any = None, **kwargs: Any) -> Any:
    """Build a path prompt with a visible completion hint."""
    if q is None:
        import questionary as q
    hint = "folders" if kwargs.get("only_directories") else "file/folder choices"
    return q.path(f"{_label(prompt)} (Tab: show {hint})", default=default, **kwargs)


def print_coloured(fragments: list[tuple[str, str]]) -> None:
    """Use native terminal output for colour; redirected output stays plain."""
    if not sys.stdout.isatty():
        print("".join(value for _, value in fragments))
        return
    from prompt_toolkit import print_formatted_text
    from prompt_toolkit.formatted_text import FormattedText
    from prompt_toolkit.output import ColorDepth

    print_formatted_text(FormattedText(fragments), color_depth=ColorDepth.TRUE_COLOR)


def choice(
    prompt: str,
    choices: list[str],
    default: str = "",
    *,
    labels: Mapping[str, str | list[tuple[str, str]]] | None = None,
    message: str | None = None,
    hotkeys: bool = True,
) -> str:
    if menus_enabled():
        import questionary as q

        unique = list(dict.fromkeys(value.upper() for value in choices))
        label = message or _label(prompt)
        if set(unique) == {"Y", "N"}:
            return (
                "Y"
                if _answer(q.confirm(label, default=default.upper() == "Y"))
                else "N"
            )
        options = []
        keys = _choice_hotkeys(unique) if hotkeys else {}
        for value in unique:
            title = (labels or {}).get(value, value)
            options.append(q.Choice(title, value=value))
        return _answer(
            select(
                label,
                q=q,
                choices=options,
                default=default.upper() or None,
                hotkeys=keys,
            )
        )
    while True:
        value = input(prompt).strip() or default
        if {item.upper() for item in choices} == {"Y", "N"} and value.lower() in {
            "yes",
            "no",
        }:
            return "Y" if value.lower() == "yes" else "N"
        if value in choices:
            return value
        if value.upper() in choices:
            return value.upper()
        print(f"  Please enter one of: {', '.join(choices)}")


def text(prompt: str, default: str = "") -> str:
    if menus_enabled():
        import questionary as q

        return _answer(q.text(_label(prompt), default=default))
    return input(prompt)


def path(prompt: str, default: str = "") -> str:
    if menus_enabled():
        import questionary as q

        return _answer(path_prompt(prompt, default, q=q))
    return input(prompt)


def legacy_menu(*lines: str) -> None:
    if not menus_enabled():
        for line in lines:
            print(line)
