"""``titan u9 trigger-*`` / ``activity-*`` — trigger script and NPC activity commands."""

from __future__ import annotations

__all__ = [
    "trigger_list_cmd",
    "trigger_show_cmd",
    "trigger_opcodes_cmd",
    "activity_list_cmd",
    "activity_show_cmd",
    "activity_opcodes_cmd",
    "script_research_export_cmd",
]

import os
import sys
from types import SimpleNamespace
from typing import Annotated, Optional

import typer

from titan.u9.activity import ACTIVITY_OPCODE_CATALOGUE, U9Activities, U9ActivityError
from titan.u9.script_research import export_script_research_bundle
from titan.u9.trigger_operands import operand_summary
from titan.u9.triggers import U9Triggers, U9TriggersError, trigger_opcode_info


def _load_triggers(filepath: str) -> Optional[U9Triggers]:
    """Open static/triggers.flx, reporting the reason on failure."""
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return None
    try:
        return U9Triggers.from_file(filepath)
    except U9TriggersError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return None


def cmd_trigger_list(args: SimpleNamespace) -> int:
    """List trigger scripts with their record counts."""
    triggers = _load_triggers(args.file)
    if triggers is None:
        return 1

    try:
        entries = triggers.triggers()
    except U9TriggersError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    if not args.all:
        entries = [t for t in entries if not t.is_empty]
    shown = entries[: args.limit] if args.limit else entries

    empty = sum(1 for t in triggers.triggers() if t.is_empty)
    print(
        f"{args.file} -- {len(entries)} trigger(s) of {triggers.num_entries} slots ({empty} empty)"
    )
    print(f"{'TriggerID':>10}  {'Records':>7}  {'Slack':>5}  {'Term':>5}  Opcodes")
    print("-" * 66)
    for t in shown:
        term = "yes" if t.terminated else "NO"
        ops = " ".join(f"{o:#04x}" for o in t.opcodes[:6])
        if len(t.opcodes) > 6:
            ops += " ..."
        print(
            f"{t.trigger_id:>10}  {len(t.records):>7}  {t.slack_records:>5}  {term:>5}  {ops}"
        )
    if args.limit and len(entries) > args.limit:
        print(f"... ({len(entries) - args.limit} more; raise --limit to see more)")
    return 0


def cmd_trigger_show(args: SimpleNamespace) -> int:
    """Dump one trigger script's records."""
    triggers = _load_triggers(args.file)
    if triggers is None:
        return 1

    try:
        trigger = triggers.trigger(args.id)
    except U9TriggersError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    if trigger is None:
        print(f"Trigger {args.id} is an unused slot.")
        return 0

    print(f"{args.file} -- trigger {trigger.trigger_id}")
    if trigger.is_empty:
        print("  (empty -- the terminator is the first record)")
    if not trigger.terminated:
        print(
            "  WARNING: no 0xFF terminator; the record list runs to the end of the entry"
        )
    if trigger.slack_records:
        print(
            f"  {trigger.slack_records} stale record(s) after the terminator (preserved)"
        )
    if trigger.records:
        print(
            f"  {'#':>3}  {'Opcode':>6}  {'Arg0':>5}  {'Arg1':>6}  {'Arg2':>6}  Meaning"
        )
        print("  " + "-" * 78)
        for index, r in enumerate(trigger.records):
            print(
                f"  {index:>3}  {r.opcode:>#6x}  {r.arg0:>5}  {r.arg1:>6}  "
                f"{r.arg2:>6}  {r.semantic_name}"
            )
            summary = operand_summary(r.opcode, r.arg0, r.arg1, r.arg2)
            if summary:
                print(f"  {'':>3}  {'':>6}  {'':>5}  {'':>6}  {'':>6}    {summary}")
    for index, label in trigger.unresolved_branch_labels():
        print(
            f"  NOTE: record {index} branches to label {label}, which this trigger "
            f"does not contain; the script ends there"
        )
    print(
        "  Decoded operands are views over the stored words; 'unread' bits are "
        "never read by the retail game, 'unclassified' bits are not yet traced."
    )
    return 0


def cmd_trigger_opcodes(args: SimpleNamespace) -> int:
    """Report how often each trigger opcode appears -- a starting point for decoding them."""
    triggers = _load_triggers(args.file)
    if triggers is None:
        return 1

    try:
        histogram = triggers.opcode_histogram()
        unterminated = triggers.unterminated_trigger_ids()
    except U9TriggersError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    total = sum(histogram.values())
    print(f"{args.file} -- {total} body record(s), {len(histogram)} distinct opcode(s)")
    if unterminated:
        print(f"  unterminated trigger(s): {unterminated}")
    print(f"{'Opcode':>7}  {'Count':>7}  {'Share':>7}  Meaning")
    print("-" * 72)
    rows = histogram.most_common(args.limit) if args.limit else histogram.most_common()
    for opcode, count in rows:
        info = trigger_opcode_info(opcode)
        meaning = info.meaning if info is not None else "unknown"
        print(f"{opcode:>#7x}  {count:>7}  {100 * count / total:>6.2f}%  {meaning}")
    if args.limit and len(histogram) > args.limit:
        print(f"... ({len(histogram) - args.limit} more; raise --limit to see more)")
    return 0


def _load_activities(filepath: str) -> Optional[U9Activities]:
    """Open static/activity.flx, reporting the reason on failure."""
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return None
    try:
        return U9Activities.from_file(filepath)
    except U9ActivityError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return None


def cmd_activity_list(args: SimpleNamespace) -> int:
    """List activity sets with their record counts and names."""
    activities = _load_activities(args.file)
    if activities is None:
        return 1

    try:
        entries = activities.activities()
        incomplete = activities.incomplete_activity_ids()
    except U9ActivityError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    shown = entries[: args.limit] if args.limit else entries
    print(
        f"{args.file} -- {len(entries)} activity set(s) of {activities.num_entries} slots"
    )
    if incomplete:
        print(f"  entries that did not parse cleanly: {incomplete}")
    print(f"{'ID':>5}  {'Records':>7}  {'Steps':>5}  Names")
    print("-" * 72)
    for a in shown:
        steps = sum(len(r.steps) for r in a.records)
        names = ", ".join(a.names[:4])
        if len(a.names) > 4:
            names += ", ..."
        print(f"{a.activity_id:>5}  {len(a.records):>7}  {steps:>5}  {names}")
    if args.limit and len(entries) > args.limit:
        print(f"... ({len(entries) - args.limit} more; raise --limit to see more)")
    return 0


def cmd_activity_show(args: SimpleNamespace) -> int:
    """Dump one activity set's records and steps."""
    activities = _load_activities(args.file)
    if activities is None:
        return 1

    try:
        activity = activities.activity(args.id)
    except U9ActivityError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    if activity is None:
        print(f"Activity {args.id} is an unused slot.")
        return 0

    print(f"{args.file} -- activity {activity.activity_id}")
    print(
        f"  {len(activity.records)} of {activity.declared_record_count} declared record(s), "
        f"{activity.payload_length}-byte payload"
    )
    if activity.trailing_bytes:
        print(
            f"  WARNING: {activity.trailing_bytes} byte(s) left over after the last record"
        )
    for record in activity.records:
        print(f"  [{record.ordinal}] {record.name}")
        if not record.terminated:
            print(
                "       WARNING: no 0xFF step; the record runs to the end of the entry"
            )
        for index, step in enumerate(record.steps):
            duration = (
                ""
                if step.duration_value is None
                else f" effective_duration={step.duration_value}"
            )
            print(
                f"       {index:>2}  opcode {step.opcode:#04x} "
                f"{step.semantic_name}: parameter_0={step.parameter_0} "
                f"parameter_1={step.parameter_1} minute={step.scheduled_minute} "
                f"duration_code={step.duration_code}{duration}  "
                f"raw={step.to_bytes().hex(' ')}"
            )
            kind = step.npc_action_kind
            if kind is not None:
                label = kind.name or "uncatalogued value"
                effect = "" if kind.performed else " -- starts nothing in 1.19F"
                print(f"           action kind {kind.value}: {label}{effect}")
        if not record.steps:
            print("       (no steps)")
    if activity.starts_with_default_activity:
        print(
            "  NOTE: the first record is not ordinal 1, so the NPC runs its queued or "
            "default activity until something switches to one of these records"
        )
    for ordinal, index, target in activity.unresolved_sequence_references():
        print(
            f"  NOTE: record [{ordinal}] step {index} targets ordinal {target}, which "
            f"this set lacks; the runtime restarts the set at ordinal 1"
        )
    print(
        "  Opcode meanings, the fixed four-word operand layout, the action-kind "
        "catalogue and the ordinal fallbacks are retail-confirmed."
    )
    return 0


def cmd_activity_opcodes(args: SimpleNamespace) -> int:
    """Report step opcode and activity name frequency across the archive."""
    activities = _load_activities(args.file)
    if activities is None:
        return 1

    try:
        opcodes = activities.opcode_histogram()
        names = activities.name_histogram()
    except U9ActivityError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    total = sum(opcodes.values())
    print(
        f"{args.file} -- {total} step(s), {len(opcodes)} distinct opcode(s), "
        f"{len(names)} distinct name(s)"
    )
    print(f"{'Opcode':>7}  {'Count':>7}  {'Share':>7}  Meaning")
    print("-" * 72)
    catalogued = {info.opcode for info in ACTIVITY_OPCODE_CATALOGUE}
    for info in ACTIVITY_OPCODE_CATALOGUE:
        count = opcodes[info.opcode]
        share = 0.0 if total == 0 else 100 * count / total
        print(f"{info.opcode:>#7x}  {count:>7}  {share:>6.2f}%  {info.meaning}")
    for opcode in sorted(set(opcodes) - catalogued):
        count = opcodes[opcode]
        share = 0.0 if total == 0 else 100 * count / total
        print(f"{opcode:>#7x}  {count:>7}  {share:>6.2f}%  unknown")
    print("")
    print(f"{'Count':>7}  Name")
    print("-" * 30)
    for name, count in names.most_common(args.limit or 15):
        print(f"{count:>7}  {name}")
    return 0


def cmd_script_research_export(args: SimpleNamespace) -> int:
    """Export trigger/activity evidence tables for external analysis."""
    triggers = _load_triggers(args.triggers)
    activities = _load_activities(args.activities)
    if triggers is None or activities is None:
        return 1

    try:
        paths = export_script_research_bundle(
            triggers,
            activities,
            args.output,
            source_files={
                "triggers": args.triggers,
                "activities": args.activities,
            },
        )
    except (OSError, U9TriggersError, U9ActivityError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(f"Wrote {len(paths)} script research file(s) to {args.output}")
    for path in paths:
        print(f"  {path}")
    return 0


def trigger_list_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/triggers.flx")],
    all: Annotated[
        bool,
        typer.Option("-a", "--all", help="Include empty triggers"),
    ] = False,
    limit: Annotated[
        Optional[int],
        typer.Option("-n", "--limit", help="Maximum rows to print"),
    ] = None,
) -> None:
    """List U9 trigger scripts; the trigger ID is the FLX entry index."""
    raise SystemExit(cmd_trigger_list(SimpleNamespace(file=file, all=all, limit=limit)))


def trigger_show_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/triggers.flx")],
    id: Annotated[
        int, typer.Argument(help="Trigger ID, as carried by a runtime entity")
    ],
) -> None:
    """Dump one U9 trigger script's records."""
    raise SystemExit(cmd_trigger_show(SimpleNamespace(file=file, id=id)))


def trigger_opcodes_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/triggers.flx")],
    limit: Annotated[
        Optional[int],
        typer.Option("-n", "--limit", help="Maximum opcodes to print"),
    ] = None,
) -> None:
    """Report trigger opcode frequency across the whole archive."""
    raise SystemExit(cmd_trigger_opcodes(SimpleNamespace(file=file, limit=limit)))


def activity_list_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/activity.flx")],
    limit: Annotated[
        Optional[int],
        typer.Option("-n", "--limit", help="Maximum rows to print"),
    ] = None,
) -> None:
    """List U9 NPC activity sets and the named sequences they hold."""
    raise SystemExit(cmd_activity_list(SimpleNamespace(file=file, limit=limit)))


def activity_show_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/activity.flx")],
    id: Annotated[int, typer.Argument(help="Activity set ID (the FLX entry index)")],
) -> None:
    """Dump one U9 activity set's named records and their steps."""
    raise SystemExit(cmd_activity_show(SimpleNamespace(file=file, id=id)))


def activity_opcodes_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/activity.flx")],
    limit: Annotated[
        Optional[int],
        typer.Option("-n", "--limit", help="Maximum names to print"),
    ] = None,
) -> None:
    """Report U9 activity step-opcode and sequence-name frequency."""
    raise SystemExit(cmd_activity_opcodes(SimpleNamespace(file=file, limit=limit)))


def script_research_export_cmd(
    triggers: Annotated[str, typer.Argument(help="Path to static/triggers.flx")],
    activities: Annotated[str, typer.Argument(help="Path to static/activity.flx")],
    output: Annotated[
        str,
        typer.Option(
            "-o", "--output", help="Directory for CSV and JSON evidence tables"
        ),
    ] = "u9-script-research",
) -> None:
    """Export lossless trigger/activity evidence tables for external analysis."""
    raise SystemExit(
        cmd_script_research_export(
            SimpleNamespace(
                triggers=triggers,
                activities=activities,
                output=output,
            )
        )
    )
