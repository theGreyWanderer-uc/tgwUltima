"""Lint/validate extracted dialogue JSON files (Phase 2 AST format)."""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter

issues = []
totals = Counter()

VALID_TYPES = {
    "Bark", "DialogueLine", "Ask", "MenuSet", "MenuAdd", "MenuUnion",
    "MenuRemove", "StringAssign", "SetFlag", "Call", "BeginConversation",
    "EndConversation", "IfStatement", "ConversationLoop", "SuspendAssign",
    "Jump", "Unknown",
}


def lint_nodes(fname, func_name, nodes, written_flags):
    """Recursively validate a list of AST nodes."""
    for i, node in enumerate(nodes):
        nid = node.get("id", f"?_{i}")
        ntype = node.get("type", "")
        totals[ntype] += 1

        # Node type validation
        if ntype not in VALID_TYPES:
            issues.append((fname, "INVALID_NODE_TYPE", f"{func_name}/{nid}: unknown type '{ntype}'"))

        # Bark/DialogueLine must have text
        if ntype in ("Bark", "DialogueLine"):
            text = node.get("text", "")
            if not text:
                issues.append((fname, "EMPTY_SPEECH", f"{func_name}/{nid}: empty text"))
            elif len(text) > 500:
                issues.append((fname, "LONG_SPEECH", f"{func_name}/{nid}: {len(text)} chars"))

            if "\\x" in text or "\\u" in text:
                issues.append((fname, "ESCAPE_IN_TEXT", f"{func_name}/{nid}: escape sequence in text"))

            opens = text.count("{")
            closes = text.count("}")
            if opens != closes:
                issues.append((fname, "UNMATCHED_BRACES", f"{func_name}/{nid}: {opens} {{ vs {closes} }}"))

        # Menu ops should have options
        if ntype in ("MenuSet", "MenuUnion", "MenuAdd", "MenuRemove"):
            if not node.get("options"):
                issues.append((fname, "EMPTY_MENU", f"{func_name}/{nid}: no options"))

        # SetFlag should have flag and value
        if ntype == "SetFlag":
            if not node.get("flag"):
                issues.append((fname, "EMPTY_FLAG_SET", f"{func_name}/{nid}: no flag name"))
            else:
                written_flags.add(node["flag"])

        # Call should have target
        if ntype == "Call":
            if not node.get("target"):
                issues.append((fname, "EMPTY_CALL", f"{func_name}/{nid}: no call target"))

        # Recurse into nested structures
        if ntype == "IfStatement":
            lint_nodes(fname, func_name, node.get("then", []), written_flags)
            lint_nodes(fname, func_name, node.get("else", []), written_flags)
            for eif in node.get("else_ifs", []):
                lint_nodes(fname, func_name, eif.get("body", []), written_flags)

        if ntype == "ConversationLoop":
            lint_nodes(fname, func_name, node.get("body", []), written_flags)


def count_nodes_recursive(nodes):
    """Count total nodes including nested children."""
    total = len(nodes)
    for node in nodes:
        ntype = node.get("type", "")
        if ntype == "IfStatement":
            total += count_nodes_recursive(node.get("then", []))
            total += count_nodes_recursive(node.get("else", []))
            for eif in node.get("else_ifs", []):
                total += count_nodes_recursive(eif.get("body", []))
        elif ntype == "ConversationLoop":
            total += count_nodes_recursive(node.get("body", []))
    return total


def count_type_recursive(nodes, target_type):
    """Count nodes of a specific type including nested children."""
    count = sum(1 for n in nodes if n.get("type") == target_type)
    for node in nodes:
        ntype = node.get("type", "")
        if ntype == "IfStatement":
            count += count_type_recursive(node.get("then", []), target_type)
            count += count_type_recursive(node.get("else", []), target_type)
            for eif in node.get("else_ifs", []):
                count += count_type_recursive(eif.get("body", []), target_type)
        elif ntype == "ConversationLoop":
            count += count_type_recursive(node.get("body", []), target_type)
    return count


def run_lint(json_dir: str) -> int:
    global issues, totals
    issues = []
    totals = Counter()
    skipped_files = []

    files = sorted(
        f for f in os.listdir(json_dir)
        if f.endswith('.json') and f.startswith('U8P_')
    )

    for fname in files:
        path = os.path.join(json_dir, fname)
        with open(path, encoding='utf-8') as f:
            d = json.load(f)

        # Skip aggregate exports (e.g. all_dialogue.json) or any non-object JSON root.
        if fname == "all_dialogue.json" or isinstance(d, list):
            skipped_files.append(fname)
            continue

        if not isinstance(d, dict):
            skipped_files.append(fname)
            continue

        npc = d.get("npc", "?")

        # 1. Schema checks
        for key in ("npc", "sourceFile", "functions", "flags", "stats", "hasDialogue"):
            if key not in d:
                issues.append((fname, "MISSING_KEY", f"Top-level key '{key}' missing"))

        # 2. Function checks
        written_flags = set()
        for func_name, func in d.get("functions", {}).items():
            if "type" not in func:
                issues.append((fname, "MISSING_FUNC_TYPE", f"{func_name} has no 'type'"))
            if "nodes" not in func:
                issues.append((fname, "MISSING_NODES", f"{func_name} has no 'nodes'"))
                continue

            lint_nodes(fname, func_name, func["nodes"], written_flags)

        # 3. Stats consistency check
        stats = d.get("stats", {})
        actual_nodes = sum(
            count_nodes_recursive(func.get("nodes", []))
            for func in d.get("functions", {}).values()
        )
        if stats.get("totalNodes", 0) != actual_nodes:
            issues.append((fname, "STATS_MISMATCH", f"totalNodes {stats.get('totalNodes')} != actual {actual_nodes}"))

        actual_barks = sum(
            count_type_recursive(func.get("nodes", []), "Bark")
            for func in d.get("functions", {}).values()
        )
        if stats.get("barkCount", 0) != actual_barks:
            issues.append((fname, "STATS_MISMATCH", f"barkCount {stats.get('barkCount')} != actual {actual_barks}"))

        actual_dl = sum(
            count_type_recursive(func.get("nodes", []), "DialogueLine")
            for func in d.get("functions", {}).values()
        )
        if stats.get("dialogueLineCount", 0) != actual_dl:
            issues.append((fname, "STATS_MISMATCH", f"dialogueLineCount {stats.get('dialogueLineCount')} != actual {actual_dl}"))

        # 4. Flags consistency: flags in write list should appear in SetFlag nodes
        declared_write = set(d.get("flags", {}).get("write", []))
        for f in declared_write - written_flags:
            issues.append((fname, "PHANTOM_FLAG_WRITE", f"Flag '{f}' in write list but not in any SetFlag node"))
        for f in written_flags - declared_write:
            issues.append((fname, "UNDECLARED_FLAG_WRITE", f"Flag '{f}' in SetFlag node but not in write list"))

        # 5. hasDialogue consistency
        has_dialogue_funcs = any(
            func.get("type") == "dialogue"
            for func in d.get("functions", {}).values()
        )
        if d.get("hasDialogue") != has_dialogue_funcs:
            issues.append((fname, "DIALOGUE_FLAG_MISMATCH", f"hasDialogue={d.get('hasDialogue')} but dialogue funcs={has_dialogue_funcs}"))


    # Report
    issue_types = Counter(t for _, t, _ in issues)

    print(f"=== Dialogue JSON Lint Report ===")
    print(f"  Files checked:  {len(files)}")
    if skipped_files:
        print(f"  Files skipped:  {len(skipped_files)}")
    print(f"  Total issues:   {len(issues)}")
    print()

    if issue_types:
        print("Issue types:")
        for itype, count in issue_types.most_common():
            print(f"  {itype:30s} {count}")
        print()

        print("Details:")
        for fname, itype, msg in sorted(issues):
            print(f"  [{itype}] {fname}: {msg}")
    else:
        print("  No issues found!")

    print()
    print("Node type distribution:")
    for ntype, count in totals.most_common():
        print(f"  {ntype:20s} {count}")

    return 1 if issues else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("json_dir", nargs="?", default="dialogue/json")
    args = parser.parse_args(argv)
    return run_lint(args.json_dir)


if __name__ == "__main__":
    raise SystemExit(main())
