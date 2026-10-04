"""Shared Questionary prompts, with a fallback for redirected terminal input."""

from __future__ import annotations

import re
import sys
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


def select(prompt: str, *, q: Any = None, **kwargs: Any) -> Any:
    """Keep a single-choice menu's highlight on its cursor, including defaults."""
    if q is None:
        import questionary as q
    from prompt_toolkit.styles import Style
    from prompt_toolkit.output import ColorDepth
    from questionary.prompts.common import InquirerControl

    kwargs.setdefault("style", Style.from_dict({"highlighted": "bold reverse"}))
    kwargs.setdefault("color_depth", ColorDepth.TRUE_COLOR)
    question = q.select(prompt, **kwargs)
    application = getattr(question, "application", None)
    if application is not None:
        for control in application.layout.find_all_controls():
            if isinstance(control, InquirerControl):
                # Questionary marks `default` as selected as well as positioning
                # the cursor. Single-choice menus only need the cursor highlight.
                control.selected_options.clear()
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
        options = [
            q.Choice((labels or {}).get(value, value), value=value) for value in unique
        ]
        return _answer(
            select(label, q=q, choices=options, default=default.upper() or None)
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
