"""Tests for titan.u6.gamestate's party/player/clock/weather decoder.

No real game files are used here -- the fixture is a hand-built objlist
buffer matching the offsets confirmed against Nuvie's Party.cpp/
Player.cpp/GameClock.cpp/Weather.cpp. See titan/u6/gamestate.py's module
docstring for the real-data validation: a real new-game objlist decodes
to the starting party (Avatar/Dupre/Shamino/Iolo at actor IDs 1-4,
matching titan.u6.converse's default symbol table) and July 4, year 161,
8:00 -- Ultima VI's actual in-lore start date.
"""

from __future__ import annotations

import struct
import unittest

from titan.u6.gamestate import (
    OFFSET_ALCOHOL,
    OFFSET_GAMETIME,
    OFFSET_GARGISH_LANG,
    OFFSET_GENDER,
    OFFSET_KARMA,
    OFFSET_NUM_IN_PARTY,
    OFFSET_PARTY_COMBAT_MODE,
    OFFSET_PARTY_NAMES,
    OFFSET_PARTY_ROSTER,
    OFFSET_QUEST_FLAG,
    OFFSET_REST_COUNTER,
    OFFSET_SOLO_MODE,
    OFFSET_WIND_DIR,
    PARTY_MODE_SENTINEL,
    PARTY_NAME_SLOT_SIZE,
    REQUIRED_SIZE,
    U6GameState,
    U6GameStateError,
)


def _make_objlist() -> bytearray:
    return bytearray(REQUIRED_SIZE)


def _set_party(buf: bytearray, members: list[tuple[str, int]]) -> None:
    buf[OFFSET_NUM_IN_PARTY] = len(members)
    for i, (name, actor_id) in enumerate(members):
        off = OFFSET_PARTY_NAMES + i * PARTY_NAME_SLOT_SIZE
        name_bytes = name.encode("latin-1") + b"\x00"
        buf[off:off + len(name_bytes)] = name_bytes
        buf[OFFSET_PARTY_ROSTER + i] = actor_id


class PartyTests(unittest.TestCase):
    def test_no_party_members(self):
        buf = _make_objlist()
        state = U6GameState.parse(bytes(buf))
        self.assertEqual(state.party.num_members, 0)

    def test_parses_party_names_and_roster(self):
        buf = _make_objlist()
        _set_party(buf, [("Avatar", 1), ("Dupre", 2), ("Shamino", 3), ("Iolo", 4)])
        state = U6GameState.parse(bytes(buf))
        self.assertEqual(state.party.num_members, 4)
        names = [(m.name, m.actor_id) for m in state.party.members]
        self.assertEqual(names, [("Avatar", 1), ("Dupre", 2), ("Shamino", 3), ("Iolo", 4)])

    def test_combat_mode_flag(self):
        buf = _make_objlist()
        buf[OFFSET_PARTY_COMBAT_MODE] = 1
        state = U6GameState.parse(bytes(buf))
        self.assertTrue(state.party.in_combat_mode)

    def test_rejects_data_too_short_for_declared_party_size(self):
        # REQUIRED_SIZE is sized for the later (party-unrelated) fields, so
        # only a truly maximal party count actually overruns the buffer.
        buf = _make_objlist()
        buf[OFFSET_NUM_IN_PARTY] = 255
        with self.assertRaises(U6GameStateError):
            U6GameState.parse(bytes(buf))


class ClockTests(unittest.TestCase):
    def test_gametime_decodes_correctly(self):
        buf = _make_objlist()
        buf[OFFSET_GAMETIME:OFFSET_GAMETIME + 4] = bytes([0, 8, 4, 7])  # minute,hour,day,month
        struct.pack_into("<H", buf, OFFSET_GAMETIME + 4, 161)
        state = U6GameState.parse(bytes(buf))
        self.assertEqual(state.clock.date_string(), "July 4, year 161")
        self.assertEqual(state.clock.time_string(), "08:00")

    def test_rest_counter(self):
        buf = _make_objlist()
        buf[OFFSET_REST_COUNTER] = 5
        state = U6GameState.parse(bytes(buf))
        self.assertEqual(state.clock.rest_counter, 5)

    def test_unknown_month_falls_back_to_number(self):
        buf = _make_objlist()
        buf[OFFSET_GAMETIME:OFFSET_GAMETIME + 4] = bytes([0, 0, 1, 99])
        state = U6GameState.parse(bytes(buf))
        self.assertIn("99", state.clock.date_string())


class PlayerStateTests(unittest.TestCase):
    def test_karma_alcohol_quest_flag(self):
        buf = _make_objlist()
        buf[OFFSET_KARMA] = 75
        buf[OFFSET_ALCOHOL] = 3
        buf[OFFSET_QUEST_FLAG] = 1
        state = U6GameState.parse(bytes(buf))
        self.assertEqual(state.player.karma, 75)
        self.assertEqual(state.player.alcohol, 3)
        self.assertEqual(state.player.quest_flag, 1)

    def test_gargish_flag(self):
        buf = _make_objlist()
        buf[OFFSET_GARGISH_LANG] = 1
        state = U6GameState.parse(bytes(buf))
        self.assertTrue(state.player.knows_gargish)

    def test_gender_word(self):
        buf = _make_objlist()
        buf[OFFSET_GENDER] = 0
        self.assertEqual(U6GameState.parse(bytes(buf)).player.gender_word, "male")
        buf[OFFSET_GENDER] = 1
        self.assertEqual(U6GameState.parse(bytes(buf)).player.gender_word, "female")

    def test_full_party_mode_sentinel(self):
        buf = _make_objlist()
        buf[OFFSET_SOLO_MODE] = PARTY_MODE_SENTINEL
        state = U6GameState.parse(bytes(buf))
        self.assertFalse(state.player.solo_mode)
        self.assertIsNone(state.player.solo_member_index)

    def test_solo_mode_with_member_index(self):
        buf = _make_objlist()
        buf[OFFSET_SOLO_MODE] = 2
        state = U6GameState.parse(bytes(buf))
        self.assertTrue(state.player.solo_mode)
        self.assertEqual(state.player.solo_member_index, 2)


class WeatherTests(unittest.TestCase):
    def test_wind_direction_table(self):
        buf = _make_objlist()
        for raw, expected in enumerate(["N", "NE", "E", "SE", "S", "SW", "W", "NW"]):
            buf[OFFSET_WIND_DIR] = raw
            self.assertEqual(U6GameState.parse(bytes(buf)).wind_direction, expected)

    def test_calm_wind_sentinel(self):
        buf = _make_objlist()
        buf[OFFSET_WIND_DIR] = 0xFF
        state = U6GameState.parse(bytes(buf))
        self.assertIsNone(state.wind_direction)


class ErrorHandlingTests(unittest.TestCase):
    def test_rejects_short_data(self):
        with self.assertRaises(U6GameStateError):
            U6GameState.parse(b"\x00" * 100)


if __name__ == "__main__":
    unittest.main()
