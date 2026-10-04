"""Public help-contract tests for the U9 command set."""

from __future__ import annotations

import unittest

from click.utils import strip_ansi
from typer.testing import CliRunner

from titan.u9.cli import u9_app


class U9CliHelpContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()

    def test_every_registered_command_has_working_help(self) -> None:
        commands = ("--help",) + tuple(
            command.name for command in u9_app.registered_commands
        )
        for command in commands:
            with self.subTest(command=command):
                arguments = [command] if command == "--help" else [command, "--help"]
                result = self.runner.invoke(u9_app, arguments)
                self.assertEqual(result.exit_code, 0, result.output)

    def test_animation_commands_take_no_external_name_table(self) -> None:
        # Clip labels come from the authoring path stored in anim.flx itself.
        for command in (
            "animation-list",
            "animation-show",
            "animation-library-plan",
            "animation-model-report",
            "animation-pose-export",
            "animation-bundle-export",
            "animation-set-export",
            "avatar-animation-library-export",
        ):
            with self.subTest(command=command):
                result = self.runner.invoke(u9_app, [command, "--help"])
                self.assertEqual(result.exit_code, 0, result.output)
                self.assertNotIn("--motion-ids", strip_ansi(result.output))

    def test_script_research_command_remains_available(self) -> None:
        result = self.runner.invoke(u9_app, ["script-research-export", "--help"])

        self.assertEqual(result.exit_code, 0, result.output)
        help_text = strip_ansi(result.output)
        self.assertIn("--output", help_text)
        self.assertIn("TRIGGERS", help_text.upper())
        self.assertIn("ACTIVITIES", help_text.upper())


if __name__ == "__main__":
    unittest.main()
