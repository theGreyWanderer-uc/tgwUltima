"""Corpus test: entity triggers are extra-data tags 62/59; ``+0x1A`` is not one.

The retail trigger executor reads object properties 0x3E (tag 62) and 0x3B
(tag 59) and picks a 16-bit half by phase. If that reading is right, the
halves should overwhelmingly be trigger IDs used in ``static/triggers.flx``,
and the old ``+0x1A`` "trigger ID" should almost never equal one of them.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from titan.u9.nonfixed import U9Nonfixed
from titan.u9.triggers import U9Triggers

ROOT = Path(__file__).resolve().parents[2] / "u9data" / "gameData_u9"


@unittest.skipUnless(
    (ROOT / "static" / "triggers.flx").is_file() and (ROOT / "runtime").is_dir(),
    "retail 1.19F runtime and static data not available",
)
class RetailEntityTriggerTests(unittest.TestCase):
    def test_tag_halves_are_trigger_ids_and_link_is_not(self) -> None:
        used = set(U9Triggers.from_file(ROOT / "static" / "triggers.flx").used_trigger_ids())
        halves = hits = tagged = link_matches = 0
        for path in sorted((ROOT / "runtime").glob("NONFIXED.*")):
            region = U9Nonfixed.from_file(path)
            for entity in region.allocated_entities():
                ids = region.entity_triggers(entity).ids
                if not ids:
                    continue
                tagged += 1
                link_matches += entity.link in ids
                halves += len(ids)
                hits += sum(tid in used for tid in ids)
        self.assertGreater(tagged, 10_000)
        self.assertGreater(hits / halves, 0.9)
        self.assertLessEqual(link_matches, 1)


if __name__ == "__main__":
    unittest.main()
