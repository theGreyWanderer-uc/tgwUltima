"""Tests for Ultima IX's shared model/animation node-name registry."""

from __future__ import annotations

import unittest

from titan.u9.node_registry import U9NodeRegistry, U9NodeRegistryError


class NodeRegistryTests(unittest.TestCase):
    def test_comments_and_node_names_are_parsed(self) -> None:
        registry = U9NodeRegistry.from_text(
            "// generated\n\n1 BIP01\n15 HEAD\n329 CAMERA01_TARGET.LWO\n"
        )

        self.assertEqual(len(registry), 3)
        self.assertEqual(registry.name_for(1), "BIP01")
        self.assertEqual(registry.name_for(329), "CAMERA01_TARGET.LWO")
        self.assertIsNone(registry.name_for(0))

    def test_duplicate_node_id_is_rejected(self) -> None:
        with self.assertRaisesRegex(U9NodeRegistryError, "duplicate node ID 1"):
            U9NodeRegistry.from_text("1 ROOT\n1 OTHER_ROOT\n")

    def test_non_mapping_line_is_rejected(self) -> None:
        with self.assertRaisesRegex(U9NodeRegistryError, "decimal_id name"):
            U9NodeRegistry.from_text("1\n")


if __name__ == "__main__":
    unittest.main()
