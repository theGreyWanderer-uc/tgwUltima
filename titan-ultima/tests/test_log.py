"""Library log records reach the terminal the way prints used to."""

from __future__ import annotations

import logging

from titan import _log


def test_cli_logging_prints_info_and_prefixes_problems(capsys) -> None:
    _log.install_cli_logging()
    _log.install_cli_logging()  # idempotent: one handler
    logger = logging.getLogger("titan.u7.example")
    logger.info("  Written: out.shp (1,024 bytes)")
    logger.warning("TFA.DAT not found")
    logger.error("could not write")
    captured = capsys.readouterr()
    assert captured.out == "  Written: out.shp (1,024 bytes)\n"
    assert captured.err == "Warning: TFA.DAT not found\nERROR: could not write\n"
    handlers = [
        h
        for h in logging.getLogger("titan").handlers
        if isinstance(h, _log._TerminalHandler)
    ]
    assert len(handlers) == 1


def test_records_still_reach_other_handlers(caplog) -> None:
    with caplog.at_level(logging.INFO, logger="titan"):
        logging.getLogger("titan.u8.example").info("progress")
    assert [r.getMessage() for r in caplog.records] == ["progress"]
