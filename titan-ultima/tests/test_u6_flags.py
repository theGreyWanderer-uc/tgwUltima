"""Tests for titan.u6.flags's story-flag read/compare/write tool.

No real game files are used here -- fixtures are hand-built objlist
buffers matching the offsets confirmed against Nuvie's ConverseInterpret.cpp
(talk_flags) and Converse.cpp/u6converse.txt (quest_flag, knows_gargish).
See titan/u6/flags.py's module docstring for why "story flags" here means
the 256 actors' talk_flags plus those two singleton bytes, not one big
global-flags table (Ultima 6 doesn't have one).
"""

from __future__ import annotations

import unittest

from titan.u6.actor import NUM_ACTORS, OFFSET_TALK_FLAGS
from titan.u6.flags import (
    U6FlagsError,
    compare_flags,
    read_talk_flags,
    set_gargish_flag,
    set_quest_flag,
    set_talk_flag,
)
from titan.u6.gamestate import OFFSET_GARGISH_LANG, OFFSET_QUEST_FLAG
from titan.u6.gamestate import REQUIRED_SIZE as GAMESTATE_REQUIRED_SIZE


def _make_objlist() -> bytearray:
    return bytearray(GAMESTATE_REQUIRED_SIZE)


class ReadTalkFlagsTests(unittest.TestCase):
    def test_reads_every_actor(self):
        buf = _make_objlist()
        buf[OFFSET_TALK_FLAGS + 5] = 0b00100100
        flags = read_talk_flags(bytes(buf))
        self.assertEqual(len(flags), NUM_ACTORS)
        self.assertEqual(flags[5], 0b00100100)
        self.assertEqual(flags[0], 0)


class SetTalkFlagTests(unittest.TestCase):
    def test_sets_bit(self):
        buf = _make_objlist()
        set_talk_flag(buf, actor_id=10, index=3, value=True)
        self.assertEqual(buf[OFFSET_TALK_FLAGS + 10], 0b00001000)

    def test_clears_bit_without_disturbing_others(self):
        buf = _make_objlist()
        buf[OFFSET_TALK_FLAGS + 10] = 0xFF
        set_talk_flag(buf, actor_id=10, index=3, value=False)
        self.assertEqual(buf[OFFSET_TALK_FLAGS + 10], 0xFF & ~0b00001000)

    def test_rejects_out_of_range_actor(self):
        buf = _make_objlist()
        with self.assertRaises(U6FlagsError):
            set_talk_flag(buf, actor_id=256, index=0, value=True)

    def test_rejects_out_of_range_index(self):
        buf = _make_objlist()
        with self.assertRaises(U6FlagsError):
            set_talk_flag(buf, actor_id=0, index=8, value=True)

    def test_rejects_buffer_too_short(self):
        buf = bytearray(10)
        with self.assertRaises(U6FlagsError):
            set_talk_flag(buf, actor_id=0, index=0, value=True)


class SetGlobalFlagTests(unittest.TestCase):
    def test_set_quest_flag(self):
        buf = _make_objlist()
        set_quest_flag(buf, 1)
        self.assertEqual(buf[OFFSET_QUEST_FLAG], 1)

    def test_set_gargish_flag_true(self):
        buf = _make_objlist()
        set_gargish_flag(buf, True)
        self.assertEqual(buf[OFFSET_GARGISH_LANG], 1)

    def test_set_gargish_flag_false(self):
        buf = _make_objlist()
        buf[OFFSET_GARGISH_LANG] = 1
        set_gargish_flag(buf, False)
        self.assertEqual(buf[OFFSET_GARGISH_LANG], 0)


class CompareFlagsTests(unittest.TestCase):
    def test_no_differences(self):
        buf = _make_objlist()
        self.assertEqual(compare_flags(bytes(buf), bytes(buf)), [])

    def test_detects_single_bit_change(self):
        a = _make_objlist()
        b = _make_objlist()
        set_talk_flag(b, actor_id=7, index=2, value=True)
        diffs = compare_flags(bytes(a), bytes(b))
        self.assertEqual(len(diffs), 1)
        d = diffs[0]
        self.assertEqual(d.kind, "talk_flag")
        self.assertEqual(d.actor_id, 7)
        self.assertEqual(d.bit, 2)
        self.assertEqual((d.before, d.after), (0, 1))

    def test_detects_multiple_bit_changes_on_same_actor(self):
        a = _make_objlist()
        b = _make_objlist()
        b[OFFSET_TALK_FLAGS + 3] = 0b00000011
        diffs = compare_flags(bytes(a), bytes(b))
        self.assertEqual(len(diffs), 2)
        self.assertEqual({d.bit for d in diffs}, {0, 1})

    def test_detects_quest_flag_change(self):
        a = _make_objlist()
        b = _make_objlist()
        set_quest_flag(b, 1)
        diffs = compare_flags(bytes(a), bytes(b))
        self.assertEqual(len(diffs), 1)
        self.assertEqual(diffs[0].kind, "quest_flag")
        self.assertEqual((diffs[0].before, diffs[0].after), (0, 1))

    def test_detects_gargish_flag_change(self):
        a = _make_objlist()
        b = _make_objlist()
        set_gargish_flag(b, True)
        diffs = compare_flags(bytes(a), bytes(b))
        self.assertEqual(len(diffs), 1)
        self.assertEqual(diffs[0].kind, "gargish_flag")

    def test_diff_str_format(self):
        a = _make_objlist()
        b = _make_objlist()
        set_talk_flag(b, actor_id=1, index=0, value=True)
        diffs = compare_flags(bytes(a), bytes(b))
        self.assertEqual(str(diffs[0]), "actor 1 talk_flag bit 0 set")


if __name__ == "__main__":
    unittest.main()
