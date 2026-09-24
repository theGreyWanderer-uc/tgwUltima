"""Public help-contract tests for the U9 command set."""

from __future__ import annotations

import unittest

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

    def test_animation_name_input_option_remains_available(self) -> None:
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
                self.assertIn("--motion-ids", result.output)
                normalized_help = " ".join(result.output.casefold().split())
                self.assertIn("animation-name", normalized_help)
                self.assertIn("table", normalized_help)

    def test_script_research_command_remains_available(self) -> None:
        result = self.runner.invoke(u9_app, ["script-research-export", "--help"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("--output", result.output)
        self.assertIn("TRIGGERS", result.output.upper())
        self.assertIn("ACTIVITIES", result.output.upper())


if __name__ == "__main__":
    unittest.main()
