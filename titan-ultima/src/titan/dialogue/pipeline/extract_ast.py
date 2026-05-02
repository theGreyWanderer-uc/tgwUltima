"""
Phase 2 — Dialogue Extractor with AST parsing.
"""
import json
import os
import re
import sys
import csv
from dataclasses import dataclass, field
from typing import Optional

EVENT_TYPES = {"0x0207": "use", "0x0208": "look", "0x0215": "schedule", "0x021B": "enterFastArea", "0x021C": "leaveFastArea", "0x021D": "cast", "0x022E": "AvatarStoleSomething", "0x020D": "func0D"}

# Weapon damage type flags (from WeaponInfo.h)
DMG_FLAGS = {
    0x0001: "normal",
    0x0002: "blade",
    0x0004: "blunt",
    0x0008: "fire",
    0x0010: "undead",
    0x0020: "magic",
    0x0040: "slayer",
    0x0080: "pierce",
    0x0100: "falling",
}

def _decode_damage_type(val):
    """Decode a damage_type bitmask into a list of flag names."""
    flags = []
    for bit, name in sorted(DMG_FLAGS.items()):
        if val & bit:
            flags.append(name)
    return flags

OVERLAY_STYLES = {0: 'blunt', 1: 'sword', 2: 'axe', 3: 'dagger'}

def load_item_data(repo_root, classes_csv=None):
    """Load weapon/armour stats and optional class->shape mapping."""
    shape_to_weapon = {}
    shape_to_armour = {}
    class_to_shape = {}
    overlay_to_weapons = {}  # overlay_shape → [{name, style}, ...]

    # Load usecode_classes.csv for class name -> shape ID mapping.
    default_classes_csv = os.path.join(repo_root, 'src', 'titan', 'dialogue', 'pipeline', 'resources', 'usecode_classes.csv')
    chosen_classes_csv = classes_csv if classes_csv and os.path.isfile(classes_csv) else (
        default_classes_csv if os.path.isfile(default_classes_csv) else None
    )
    if chosen_classes_csv:
        with open(chosen_classes_csv, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    class_to_shape[row['Name'].strip()] = int(row['ID'].strip())
                except (ValueError, KeyError):
                    pass

    # Load u8weapons.ini
    weapons_ini = os.path.join(repo_root, 'src', 'titan', 'dialogue', 'pipeline', 'resources', 'u8weapons.ini')
    weapons_ini = weapons_ini if os.path.isfile(weapons_ini) else None
    if weapons_ini:
        _parse_item_ini(weapons_ini, shape_to_weapon, 'weapon')
        # Build overlay_shape → weapons mapping
        for sid, wdata in shape_to_weapon.items():
            ovl_shape = wdata.get('overlay_shape')
            ovl_type = wdata.get('overlay', 0)
            if ovl_shape is not None:
                overlay_to_weapons.setdefault(ovl_shape, []).append({
                    'name': wdata.get('name', '???'),
                    'style': OVERLAY_STYLES.get(ovl_type, f'type-{ovl_type}'),
                })

    # Load u8armour.ini
    armour_ini = os.path.join(repo_root, 'src', 'titan', 'dialogue', 'pipeline', 'resources', 'u8armour.ini')
    armour_ini = armour_ini if os.path.isfile(armour_ini) else None
    if armour_ini:
        _parse_item_ini(armour_ini, shape_to_armour, 'armour')

    if not chosen_classes_csv:
        print("WARN: usecode_classes.csv not found in src/titan/dialogue/pipeline/resources; itemProperties mapping will be incomplete.")
    if not weapons_ini:
        print("WARN: u8weapons.ini not found in src/titan/dialogue/pipeline/resources; weapon/overlay itemProperties will be missing.")
    if not armour_ini:
        print("WARN: u8armour.ini not found in src/titan/dialogue/pipeline/resources; armour itemProperties will be missing.")

    return shape_to_weapon, shape_to_armour, class_to_shape, overlay_to_weapons

def _parse_item_ini(filepath, shape_dict, kind):
    """Parse a Pentagram data INI file into a shape→stats dict.
    
    For weapons: one entry per shape.
    For armour: multiple frames per shape are merged — we keep the best
    armour class and any special properties (kick_bonus, type).
    """
    current_name = None
    current = {}
    def commit(name, data):
        if not name or 'shape' not in data:
            return
        sid = data['shape']
        if sid in shape_dict:
            # Merge: keep highest armour class, preserve special properties
            existing = shape_dict[sid]
            if data.get('armour', 0) > existing.get('armour', 0):
                existing['armour'] = data['armour']
            if data.get('kick_bonus'):
                existing['kick_bonus'] = data['kick_bonus']
            if data.get('type'):
                existing['type'] = data['type']
        else:
            shape_dict[sid] = {'name': name, **data}

    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or line.startswith(';'):
                continue
            if line.startswith('[') and line.endswith(']'):
                commit(current_name, current)
                current_name = line[1:-1]
                current = {}
            elif '=' in line:
                key, _, val = line.partition('=')
                key, val = key.strip(), val.strip()
                if val.startswith('0x'):
                    try: current[key] = int(val, 16)
                    except ValueError: current[key] = val
                else:
                    try: current[key] = int(val)
                    except ValueError: current[key] = val
    commit(current_name, current)

def build_item_properties(class_name, shape_to_weapon, shape_to_armour, class_to_shape, overlay_to_weapons=None):
    """If the class represents a weapon, armour, or overlay, return a properties dict."""
    shape_id = class_to_shape.get(class_name)
    if shape_id is None:
        return None

    props = {}
    weapon = shape_to_weapon.get(shape_id)
    if weapon:
        dmg_type_raw = weapon.get('damage_type', 0)
        dmg_flags = _decode_damage_type(dmg_type_raw)
        is_special = any(f in dmg_flags for f in ('magic', 'fire', 'undead', 'slayer'))
        props['weapon'] = {
            'baseDamage': weapon.get('base_damage', 0),
            'damageModifier': weapon.get('damage_mod', 0),
            'damageType': dmg_flags,
            'attackDexBonus': weapon.get('attack_dex', 0),
            'defendDexBonus': weapon.get('defend_dex', 0),
            'armourBonus': weapon.get('armour', 0),
            'isSpecial': is_special,
        }
        if weapon.get('treasure_chance') is not None:
            props['weapon']['treasureChance'] = weapon['treasure_chance']

    armour = shape_to_armour.get(shape_id)
    if armour:
        props['armour'] = {
            'armourClass': armour.get('armour', 0),
        }
        if armour.get('type'):
            props['armour']['defenseType'] = _decode_damage_type(armour['type'])
        if armour.get('kick_bonus'):
            props['armour']['kickBonus'] = armour['kick_bonus']

    # Check if this shape is a weapon overlay (animation sprite)
    if overlay_to_weapons and not weapon and not armour:
        overlay_entries = overlay_to_weapons.get(shape_id)
        if overlay_entries:
            style = overlay_entries[0]['style']  # all entries share the same style
            used_by = sorted(set(e['name'] for e in overlay_entries))
            props['overlay'] = {
                'animationStyle': style,
                'usedBy': used_by,
            }

    return props if props else None

RE_FUNC_HEADER = re.compile(r'^(process\s+)?(\w+)::(\w+)\(([^)]*)\)\s*$')
RE_OFFSET = re.compile(r'Function Start Offset:\s*(0x[\dA-Fa-f]+)')
RE_LOCALS = re.compile(r'Locals Datasize:\s*(0x[\dA-Fa-f]+)')
RE_PROCTYPE = re.compile(r'Process Type:\s*(0x[\dA-Fa-f]+)')
RE_BARK = re.compile(r'process Item::bark\((.+?)(?:,\s*pid)?,\s*(?:this|0x[\dA-Fa-f]+h?|addressof\(\w+\))\)')
RE_BARK3 = re.compile(r'process Item::bark\(\s*pid\s*,\s*(?:this|0x[\dA-Fa-f]+h?|addressof\(\w+\)|\w+)\s*,\s*str_to_ptr\("((?:[^"\\]|\\.)*)"\)\)')
RE_BARK2 = re.compile(r'process Item::bark\(\s*(?:0x[\dA-Fa-f]+h?|addressof\(\w+\))\s*,\s*str_to_ptr\("((?:[^"\\]|\\.)*)"\)\)')
RE_BARK4 = re.compile(r'process Item::bark\(\s*str_to_ptr\("((?:[^"\\]|\\.)*)"\)\s*,\s*(?:addressof\(\w+\)|0x[\dA-Fa-f]+h?)\)')
RE_BARK_AND_WAIT = re.compile(r'barkAndWait\((?:(?:0x[\dA-Fa-f]+h?)\s*,\s*)?str_to_ptr\("((?:[^"\\]|\\.)*)"\)(?:\s*,\s*(?:0x[\dA-Fa-f]+h?))?\)')
RE_ASK = re.compile(r'strptr process Item::ask\((\w+),\s*(?:this|0x[\dA-Fa-f]+h?)\)')
RE_STRCMP = re.compile(r'(\w+)\s+strcmp\s+"((?:[^"\\]|\\.)*)"')
RE_MENU_ASSIGN = re.compile(r'(\w+)\s*=\s*(\[.*?\])')
RE_MENU_UNION = re.compile(r'(\w+)\s*=\s*(\[.*?\])\s+union\s+(\w+)')
RE_MENU_ADD = re.compile(r'(\w+)\s*=\s*(\w+)\s*\+\s*(\[.*?\])')
RE_MENU_REMOVE = re.compile(r'(\w+)\s*=\s*(\w+)\s+remove\s+(\[.*?\])')
RE_FLAG_SET = re.compile(r'^(\w+)\s*=\s*(0x[\dA-Fa-f]+h?)$')
RE_SPAWN_OWN = re.compile(r'spawn\s+this->(\w+)::(\w+)\(([^)]*)\)')
RE_SPAWN_METHOD = re.compile(r'spawn\s+this->METHOD::(\w+)\(([^)]*)\)')
RE_BEGIN_CONVO = re.compile(r'METHOD::beginConversation\(\)')
RE_END_CONVO = re.compile(r'METHOD::endConversation\(\)')
RE_URANDOM = re.compile(r'urandom\((0x[\dA-Fa-f]+h?)\)')
RE_FLAG_CHECK = re.compile(r'\b(not\s+)?(\w+)\b')
RE_IF_LINE = re.compile(r'^(?:[\w\s=]+\s*=\s*)?if\((.+)\)\s*$')
RE_ELSE_IF_LINE = re.compile(r'^else\s+if\((.+)\)\s*$')
RE_ELSE_LINE = re.compile(r'^else\s*$')
RE_FLAG_COMPARE = re.compile(r'(\w+)\s*(==|!=)\s*(0x[\dA-Fa-f]+h?)')
RE_ARRAY_STRINGS = re.compile(r'"((?:[^"\\]|\\.)*)"')
RE_IS_DEAD = re.compile(r'Npc::isDead\(([^)]*)\)')
RE_JMP_NOPRINT = re.compile(r'/\*jmp_NOPRINT\((0x[0-9A-Fa-f]+)\)\*/')
RE_ELSE_ENTRY = re.compile(r'/\*else_entry\((0x[0-9A-Fa-f]+)\)\*/')
RE_EQUIP_ITEM = re.compile(r'FREE::equipItem\(([^)]*)\)')
RE_CREATE_ITEMS = re.compile(r'FREE::createItemsAtLocation\(([^)]*)\)')
RE_FIND_NEARBY = re.compile(r'FREE::findNearbyItems\(([^)]*)\)')
RE_GET_NAME = re.compile(r'getName\(\)')
RE_NUM_TO_STR = re.compile(r'numToStr\(([^)]*)\)')
RE_SUSPEND_ASSIGN = re.compile(r'^(local\d+)\s*=\s*\(word\)suspend\b')
RE_RANDOM_ASSIGN = re.compile(r'^(local\d+)\s*=\s*FREE::randomInRange0\(')

CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}

@dataclass
class FunctionInfo:
    name: str
    class_name: str
    is_process: bool
    params: Optional[str]
    process_type: str
    offset: str
    locals_size: str
    lines: list = field(default_factory=list)
    classification: str = ""
    nodes: list = field(default_factory=list)
    flags_read: set = field(default_factory=set)
    flags_write: set = field(default_factory=set)
    variable_hints: dict = field(default_factory=dict)
    shop_items: list = field(default_factory=list)

    def to_dict(self):
        d = {"name": self.name, "type": self.classification, "isProcess": self.is_process, "processType": self.process_type}
        if self.params: d["params"] = self.params
        if self.nodes: d["nodes"] = self.nodes
        if self.flags_read: d["flagsRead"] = sorted(self.flags_read)
        if self.flags_write: d["flagsWrite"] = sorted(self.flags_write)
        if self.variable_hints: d["variableHints"] = self.variable_hints
        if self.shop_items: d["shopItems"] = self.shop_items
        return d

def _extract_locals_and_params(text):
    return set(re.findall(r'\blocal\d+\b', text)), set(re.findall(r'\bparam\d+\b', text))

def infer_variable_hints(func):
    hints = {"locals": {}, "params": {}}
    def add_hint(scope, name, role, confidence, evidence):
        if scope not in ("locals", "params"): return
        table = hints[scope]
        existing = table.get(name)
        if existing is None:
            table[name] = {"role": role, "confidence": confidence, "evidence": [evidence]}
            return
        if CONFIDENCE_RANK[confidence] > CONFIDENCE_RANK[existing["confidence"]]:
            existing["role"] = role
            existing["confidence"] = confidence
        if evidence not in existing["evidence"]:
            existing["evidence"].append(evidence)
            existing["evidence"] = existing["evidence"][:4]

    for line in func.lines:
        stripped = line.strip()
        m = RE_ASK.search(stripped)
        if m and re.fullmatch(r'local\d+', m.group(1)):
            add_hint("locals", m.group(1), "menu_options", "high", "used as Item::ask options list")
        m = RE_MENU_ASSIGN.search(stripped)
        if m and re.fullmatch(r'local\d+', m.group(1)):
            add_hint("locals", m.group(1), "menu_options", "high", "assigned from array literal")
        m = RE_MENU_UNION.search(stripped)
        if m and re.fullmatch(r'local\d+', m.group(1)):
            add_hint("locals", m.group(1), "menu_options", "high", "updated via menu union")
        m = RE_MENU_ADD.search(stripped)
        if m and re.fullmatch(r'local\d+', m.group(1)):
            add_hint("locals", m.group(1), "menu_options", "high", "updated via menu add")
        m = RE_MENU_REMOVE.search(stripped)
        if m and re.fullmatch(r'local\d+', m.group(1)):
            add_hint("locals", m.group(1), "menu_options", "high", "updated via menu remove")
        m = RE_SUSPEND_ASSIGN.match(stripped)
        if m: add_hint("locals", m.group(1), "menu_choice", "high", "assigned from suspend")
        strcmp_matches = RE_STRCMP.findall(stripped)
        for var, _txt in strcmp_matches:
            if re.fullmatch(r'local\d+', var): add_hint("locals", var, "menu_choice", "high", "used in strcmp")
            elif re.fullmatch(r'param\d+', var): add_hint("params", var, "selector_param", "medium", "used in strcmp")
        m = RE_RANDOM_ASSIGN.match(stripped)
        if m: add_hint("locals", m.group(1), "random_bucket", "high", "assigned from randomInRange0")
        m = re.match(r'^(local\d+)\s*=\s*(.+)$', stripped)
        if m and "getName()" in m.group(2): add_hint("locals", m.group(1), "player_name_text", "medium", "includes getName()")
        for p in re.findall(r'\b(param\d+)\b\s*(==|!=|<=|>=|<|>)\s*(?:0x[\dA-Fa-f]+h?|\d+)', stripped):
            add_hint("params", p[0], "selector_param", "medium", "compared to literal value")
        locals_found, params_found = _extract_locals_and_params(stripped)
        for lv in locals_found:
            if lv not in hints["locals"]: add_hint("locals", lv, "temporary", "low", "referenced")
        for pv in params_found:
            if pv not in hints["params"]: add_hint("params", pv, "parameter", "low", "referenced")
    return {k: v for k, v in hints.items() if v}

def load_global_flags(symbols_path):
    flags = set()
    if symbols_path and os.path.exists(symbols_path):
        with open(symbols_path, 'r') as f:
            for row in csv.DictReader(f):
                if row.get('type') == 'global':
                    flags.add(row['name'])
    return flags

def parse_functions(text):
    lines = text.split('\n')
    functions = []
    current_func = None
    in_header_comment = False
    brace_depth = 0
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        m = RE_FUNC_HEADER.match(stripped)
        if m and brace_depth == 0:
            functions.append(FunctionInfo(
                name=m.group(3), class_name=m.group(2), is_process=m.group(1) is not None,
                params=m.group(4).strip() if m.group(4).strip() else None, process_type="", offset="", locals_size=""
            ))
            current_func = functions[-1]
            in_header_comment, brace_depth = False, 0
            i += 1
            continue

        if current_func is not None:
            brace_depth += stripped.count('{') - stripped.count('}')
            if '/*' in stripped:
                preserve = False
                if 'jmp_NOPRINT' in stripped and '*/' in stripped:
                    for j in range(i + 1, len(lines)):
                        nxt = lines[j].strip()
                        if nxt:
                            # Preserve when inside a block (next = '}') or at function-body
                            # scope with normal code following (e.g. early-guard pattern).
                            # Drop only when between a closing '}' and an 'else'/'else if'
                            # clause — the Parser attaches those naturally without the hint.
                            preserve = not nxt.startswith('else')
                            break
                elif 'else_entry' in stripped and '*/' in stripped:
                    preserve = True  # fold-emitted boundary marker; always keep
                if not preserve:
                    in_header_comment = True
            if in_header_comment:
                m2 = RE_OFFSET.search(stripped)
                if m2: current_func.offset = m2.group(1)
                m2 = RE_LOCALS.search(stripped)
                if m2: current_func.locals_size = m2.group(1)
                m2 = RE_PROCTYPE.search(stripped)
                if m2: current_func.process_type = m2.group(1)
                if '*/' in stripped: in_header_comment = False
                i += 1
                continue
            if stripped: current_func.lines.append(stripped)
            if brace_depth <= 0 and stripped == '}': current_func = None
        i += 1
    return functions

def classify_function(func, is_npc_class=False):
    if func.process_type == "0x0208":
        func.classification = "look"
        return
    body = '\n'.join(func.lines)
    has_ask = 'Item::ask(' in body
    has_bark = 'Item::bark(' in body
    has_strcmp = ' strcmp ' in body
    has_begin_convo = 'beginConversation()' in body
    # Only flag as shop when the function actually hands over an item via equipItem.
    # createItemsAtLocation is NOT a shop signal: it is also used for item-throw effects
    # (DAGGER2), tool mechanics (TROWEL digging soil), spell effects (ETHEREAG), etc.
    # The word "obsidian" alone is also not a commerce signal — it appears in place names
    # and informational barks (e.g. the Abacus coin counter).
    has_equip = 'equipItem(' in body
    # Shop = ask + strcmp + equipItem + coin payment (findNearbyItems with shape 0x008F).
    # This combination uniquely identifies commerce functions.
    has_money = 'findNearbyItems(' in body and '0x008F' in body
    if has_ask and has_strcmp and has_equip and has_money: func.classification = "shop"
    elif has_ask and has_strcmp: func.classification = "dialogue"
    elif has_ask: func.classification = "dialogue"
    elif has_bark and has_begin_convo: func.classification = "dialogue"
    elif has_bark and is_npc_class: func.classification = "monologue"
    elif func.name in ("schedule", "enterFastArea", "leaveFastArea", "cast", "AvatarStoleSomething"):
        func.classification = "behavior"
    elif func.process_type in ("0x0215", "0x021B", "0x021C", "0x021D", "0x022E"):
        func.classification = "behavior"
    else: func.classification = "utility"

def extract_bark_text(line):
    m3 = RE_BARK3.search(line)
    if m3: return m3.group(1)
    m4 = RE_BARK4.search(line)
    if m4: return m4.group(1)
    m = RE_BARK.search(line)
    if not m:
        m2 = RE_BARK2.search(line)
        if m2: return m2.group(1)
        return None
    parts = []
    for segment in re.split(r'\s*\+\s*', m.group(1)):
        segment = segment.strip()
        if segment.startswith('"') and segment.endswith('"'): parts.append(segment[1:-1])
        elif 'getName()' in segment: parts.append('{getName}')
        elif 'numToStr(' in segment:
            m2 = RE_NUM_TO_STR.search(segment)
            parts.append('{' + m2.group(1) + '}' if m2 else '{numToStr}')
        else: parts.append('{' + segment + '}')
    return ''.join(parts)

def extract_menu_items(line):
    m = re.search(r'\[([^\]]*)\]', line)
    if not m: return []
    inner = m.group(1)
    items = RE_ARRAY_STRINGS.findall(inner)
    var_refs = re.findall(r'\b(local\d+)\b', inner)
    result = list(items)
    for v in var_refs:
        if v not in result: result.append('{' + v + '}')
    return result

class Parser:
    def __init__(self, lines, global_flags, func):
        self.lines = []
        current = ""
        for line in lines:
            line = line.strip()
            if not line: continue
            if current:
                current += " " + line
            else:
                current = line
                
            if current.endswith('=') or current.endswith('+') or current.count('"') % 2 != 0 or current.count('(') > current.count(')') or current.count('[') > current.count(']'):
                continue
            self.lines.append(current)
            current = ""
        if current:
            self.lines.append(current)
            
        self.pos = 0
        self.global_flags = global_flags
        self.func = func
        self.node_counter = 0
        self.string_vars = {}

    def _eval_string_expr(self, expr):
        expr = expr.strip()
        if expr.startswith('str_to_ptr('):
            expr = expr[11:-1]
        
        m_assign = re.match(r'^(?:temp\s*=\s*)?(local\d+)\s*=\s*(.*)', expr)
        if m_assign:
            var = m_assign.group(1)
            rhs = m_assign.group(2)
            val = self._eval_string_expr(rhs)
            self.string_vars[var] = val
            return val
            
        parts = []
        for segment in re.split(r'\s*\+\s*', expr):
            segment = segment.strip()
            if not segment: continue
            if segment.startswith('"') and segment.endswith('"'):
                parts.append(segment[1:-1])
            elif 'getName()' in segment:
                parts.append('{getName}')
            elif 'numToStr(' in segment:
                m2 = RE_NUM_TO_STR.search(segment)
                parts.append('{' + m2.group(1) + '}' if m2 else '{numToStr}')
            elif segment in self.string_vars:
                parts.append(self.string_vars[segment])
            elif segment.startswith('local'):
                pass # Uninitialized local variable string concat ignored safely
            else:
                parts.append('{' + segment + '}')
        return "".join(parts)

    def next_id(self):
        self.node_counter += 1
        return f"{self.func.name}_n{self.node_counter:03d}"

    def peek(self):
        return self.lines[self.pos] if self.pos < len(self.lines) else None

    def advance(self):
        val = self.peek()
        self.pos += 1
        return val

    def parse_block(self):
        body = []
        if self.peek() == '{':
            self.advance()
            while self.peek() is not None and self.peek() != '}':
                stmt = self.parse_statement()
                if stmt is not None:
                    if isinstance(stmt, list):
                        body.extend(stmt)
                    else:
                        body.append(stmt)
            if self.peek() == '}': self.advance()
        else:
            stmt = self.parse_statement()
            if stmt is not None:
                if isinstance(stmt, list):
                    body.extend(stmt)
                else:
                    body.append(stmt)
        return body

    def parse_statement(self):
        line = self.peek()
        if line is None: return None
        if line == '}':
            self.advance()
            return None

        m_ee = RE_ELSE_ENTRY.match(line)
        if m_ee:
            self.advance()
            return {'id': self.next_id(), 'type': 'ElseEntry', 'addr': m_ee.group(1)}

        m_if = RE_IF_LINE.match(line)
        if m_if:
            self.advance()
            node = {'id': self.next_id(), 'type': 'IfStatement', 'condition': parse_condition(m_if.group(1).strip(), self.global_flags), 'then': self.parse_block(), 'else_ifs': [], 'else': []}
            while self.peek() and RE_ELSE_IF_LINE.match(self.peek()):
                elif_m = RE_ELSE_IF_LINE.match(self.advance())
                node['else_ifs'].append({'condition': parse_condition(elif_m.group(1).strip(), self.global_flags), 'body': self.parse_block()})
            if self.peek() and RE_ELSE_LINE.match(self.peek()):
                self.advance()
                node['else'] = self.parse_block()
            return self.transform_loop(node)

        self.advance()

        if '<=>' in line:
            for pre in line.split('<=>')[:-1]:
                if 'Item::bark' not in pre and 'Item::ask' not in pre:
                    self._eval_string_expr(pre)

        m3 = RE_BARK3.search(line)
        if m3: return {'id': self.next_id(), 'type': 'Bark', 'text': m3.group(1)}
        m = RE_BARK4.search(line)
        if m: return {'id': self.next_id(), 'type': 'Bark', 'text': m.group(1)}
        m = RE_BARK.search(line)      
        if m: return {'id': self.next_id(), 'type': 'Bark', 'text': self._eval_string_expr(m.group(1))}
        m = RE_BARK2.search(line)
        if m: return {'id': self.next_id(), 'type': 'Bark', 'text': m.group(1)}
        m = RE_BARK_AND_WAIT.search(line)
        if m: return {'id': self.next_id(), 'type': 'Bark', 'text': m.group(1)}

        if '=' in line and 'Item::' not in line and 'FREE::' not in line and 'strcmp' not in line and 'remove' not in line and 'union' not in line and '[' not in line:
            m_assign = re.match(r'^(?:temp\s*=\s*)?(local\d+)\s*=\s*(.*"[^"]*".*|.*getName.*|.*numToStr.*|.*\+\s*local.*)', line)
            if m_assign:
                self._eval_string_expr(line)
                return {'id': self.next_id(), 'type': 'StringAssign', 'var': m_assign.group(1), 'value': m_assign.group(2), 'raw': line}

        m = RE_ASK.search(line)
        if m: return {'id': self.next_id(), 'type': 'Ask', 'menu': m.group(1)}
        if ' remove ' in line:
            m = RE_MENU_REMOVE.search(line)
            if m: return {'id': self.next_id(), 'type': 'MenuRemove', 'target': m.group(1), 'options': extract_menu_items(line)}
        m = RE_MENU_ADD.search(line)
        if m: return {'id': self.next_id(), 'type': 'MenuAdd', 'target': m.group(1), 'options': extract_menu_items(line)}
        m = RE_MENU_UNION.search(line)
        if m: return {'id': self.next_id(), 'type': 'MenuUnion', 'target': m.group(1), 'options': extract_menu_items(line)}
        if re.match(r'\w+\s*=\s*\[', line) and ' union ' not in line and ' remove ' not in line:
            return {'id': self.next_id(), 'type': 'MenuSet', 'target': line.split('=')[0].strip(), 'options': extract_menu_items(line)}
        if RE_BEGIN_CONVO.search(line): return {'id': self.next_id(), 'type': 'BeginConversation'}
        if RE_END_CONVO.search(line): return {'id': self.next_id(), 'type': 'EndConversation'}
        m = RE_FLAG_SET.match(line)
        if m: return {'id': self.next_id(), 'type': 'SetFlag', 'flag': m.group(1), 'value': m.group(2)}
        m = RE_SPAWN_OWN.search(line)
        if m and m.group(2) not in ('beginConversation', 'endConversation'): return {'id': self.next_id(), 'type': 'Call', 'target': f"{m.group(1)}::{m.group(2)}"}
        m = RE_SPAWN_METHOD.search(line)
        if m and m.group(1) not in ('beginConversation', 'endConversation'): return {'id': self.next_id(), 'type': 'Call', 'target': f"METHOD::{m.group(1)}"}
        if '/* jmp' in line: return {'id': self.next_id(), 'type': 'Jump'}
        m = re.match(r'^(local\d+)\s*=\s*\(word\)suspend\b', line)
        if m: return {'id': self.next_id(), 'type': 'SuspendAssign', 'var': m.group(1)}
        return {'id': self.next_id(), 'type': 'Unknown', 'raw': line}

    def transform_loop(self, node):
        loop = self._is_loop_block(node.get('condition', {}).get('raw', ''), node['then'])
        if loop: return {'id': node['id'], 'type': 'ConversationLoop', 'flag': loop[0], 'exitCondition': loop[1], 'exitWhenMatched': loop[2], 'body': node['then']}

        extracted_loops = []
        new_else_ifs = []
        for elif_block in node['else_ifs']:
            loop = self._is_loop_block(elif_block.get('condition', {}).get('raw', ''), elif_block['body'])
            if loop:
                extracted_loops.append({
                    'id': self.next_id(),
                    'type': 'ConversationLoop',
                    'flag': loop[0],
                    'exitCondition': loop[1],
                    'exitWhenMatched': loop[2],
                    'body': elif_block['body'],
                })
            else:
                new_else_ifs.append(elif_block)

        node['else_ifs'] = new_else_ifs

        # Bug 1 fix: explode menu-only else-if chains into independent IFs
        if self._is_menu_only_chain(node):
            result = [{'id': node['id'], 'type': 'IfStatement',
                        'condition': node['condition'], 'then': node['then'],
                        'else_ifs': [], 'else': []}]
            for elif_block in node['else_ifs']:
                result.append({'id': self.next_id(), 'type': 'IfStatement',
                               'condition': elif_block['condition'],
                               'then': elif_block['body'],
                               'else_ifs': [], 'else': []})
            if extracted_loops:
                return result + extracted_loops
            return result

        if not extracted_loops:
            return node
        else:
            return [node] + extracted_loops

    # ------------------------------------------------------------------
    _MENU_OP_TYPES = frozenset({'MenuAdd', 'MenuSet', 'MenuRemove', 'MenuUnion', 'SetFlag'})

    def _is_menu_only_chain(self, node):
        """True when every branch body contains only menu-manipulation ops."""
        if not node.get('else_ifs'):
            return False
        if node.get('else'):
            return False
        for n in node['then']:
            if not isinstance(n, dict) or n.get('type') not in self._MENU_OP_TYPES:
                return False
        for elif_block in node['else_ifs']:
            for n in elif_block['body']:
                if not isinstance(n, dict) or n.get('type') not in self._MENU_OP_TYPES:
                    return False
        return True

    def _is_loop_block(self, cond, body):
        if not cond: return None
        # 'not localN strcmp X' — the single 'not' is the real NOT opcode from the bytecode:
        #   strcmp(choice, exit_str); NOT; jne → exits (jne jumps) when NOT(strcmp)=0 → when equal.
        #   → exitWhenMatched=True (exit when choice == exitCondition).
        # Legacy 'not not X' (two NOTs) would invert: would exit when NOT equal → exitWhenMatched=False.
        m = re.match(r'^not\s+(not\s+)?(local\d+)\s+strcmp\s+"([^"]*)"$', cond.strip())
        if not m: return None
        if any(st.get('type') == 'Ask' for st in body if isinstance(st, dict)):
            double_neg = m.group(1) is not None
            return (m.group(2), m.group(3), not double_neg)
        return None


# ---------------------------------------------------------------------------
# Bug 2 post-pass: fold early-exit branches
# ---------------------------------------------------------------------------

def _get_exit_target(body):
    """If *body* ends with an Unknown jmp_NOPRINT node, return the hex address."""
    if not body:
        return None
    last = body[-1]
    if isinstance(last, dict) and last.get('type') == 'Unknown':
        m = RE_JMP_NOPRINT.search(last.get('raw', ''))
        if m:
            return m.group(1)
    return None


def fold_early_exits(nodes):
    """Promote implicit else bodies into IfStatement.else.

    Four sub-cases handled:
    1. Inside-body ``jmp_NOPRINT`` (Arcadion-style / function-exit branches):
       All branches end with an Unknown jmp_NOPRINT node; all remaining siblings
       become the else body.
    2b. Sibling ``jmp_NOPRINT`` with matching ``else_entry`` (RHIAN-style without elif):
       ``if(cond) { body } /*jmp_NOPRINT(X)*/ <else_body> /*else_entry(X)*/`` —
       jmp_NOPRINT and else_entry have the same address.  Nodes between them are
       the implicit else; nodes after the else_entry are the shared continuation.
    3. Sibling ``jmp_NOPRINT`` with empty then, no matching else_entry (early-guard):
       ``if(cond) {} /*jmp_NOPRINT(X)*/`` — when the condition passes the function
       exits early; all remaining siblings are the implicit else (taken when the
       condition fails).
    2. ``else_entry`` annotation (Jenna-style / shared-continuation):
       fold.exe emits ``/*else_entry(X)*/`` at the start of the shared
       continuation.  Siblings between the IfStatement and that marker are
       the implicit else; siblings from the marker onward are shared.
    """
    result = []
    i = 0
    while i < len(nodes):
        node = nodes[i]

        # Skip stray ElseEntry markers (already consumed by the promoter below).
        if isinstance(node, dict) and node.get('type') == 'ElseEntry':
            i += 1
            continue

        if (isinstance(node, dict)
                and node.get('type') == 'IfStatement'
                and not node.get('else')):

            # --- Approach 1: inside-body jmp_NOPRINT (Arcadion / function-exit) ---
            target = _get_exit_target(node['then'])
            if target is not None:
                all_match = all(
                    _get_exit_target(eb['body']) == target
                    for eb in node.get('else_ifs', [])
                )
                if all_match and i + 1 < len(nodes):
                    remaining = [n for n in nodes[i + 1:]
                                 if not (isinstance(n, dict) and n.get('type') == 'ElseEntry')]
                    node['else'] = remaining
                    result.append(node)
                    return result

            # --- Approaches 2b and 3: sibling jmp_NOPRINT ---
            # jmp_NOPRINT is preserved as an Unknown sibling when it appears at
            # function-body scope (next line is not 'else'/'else if').
            if i + 1 < len(nodes):
                nxt = nodes[i + 1]
                jnp_m = (isinstance(nxt, dict) and nxt.get('type') == 'Unknown'
                         and RE_JMP_NOPRINT.match(nxt.get('raw', '')))
                if jnp_m:
                    jmp_target = RE_JMP_NOPRINT.match(nxt['raw']).group(1)
                    remaining = nodes[i + 2:]
                    # Look for an else_entry whose address matches the jmp target.
                    entry_idx = next(
                        (j for j, n in enumerate(remaining)
                         if isinstance(n, dict) and n.get('type') == 'ElseEntry'
                         and n.get('addr') == jmp_target),
                        None
                    )
                    if entry_idx is not None:
                        # Approach 2b: matching else_entry — shared-continuation split.
                        # (RHIAN if(not rhianMet) first-visit vs return-visit)
                        node['else'] = fold_early_exits(remaining[:entry_idx])
                        result.append(node)
                        rest = [n for n in remaining[entry_idx + 1:]
                                if not (isinstance(n, dict) and n.get('type') == 'ElseEntry')]
                        result.extend(fold_early_exits(rest))
                        return result
                    elif not node.get('then') and not node.get('else_ifs'):
                        # Approach 3: empty-then early-guard (jmp exits function, no else_entry).
                        # (RHIAN if(not toranDead) — conversation skipped until flag is set)
                        node['else'] = fold_early_exits(remaining)
                        result.append(node)
                        return result

            # --- Approach 2: else_entry annotation (Jenna-style / shared-continuation) ---
            # Applies when the IfStatement has else_ifs (an elif chain with jmps inside them).
            if node.get('else_ifs'):
                remaining = nodes[i + 1:]
                entry_idx = next(
                    (j for j, n in enumerate(remaining)
                     if isinstance(n, dict) and n.get('type') == 'ElseEntry'),
                    None
                )
                if entry_idx is not None:
                    # Nodes before the marker are the implicit else body.
                    node['else'] = remaining[:entry_idx]
                    result.append(node)
                    # Continue with nodes after the ElseEntry marker (shared continuation).
                    rest = remaining[entry_idx + 1:]
                    result.extend(n for n in rest
                                  if not (isinstance(n, dict) and n.get('type') == 'ElseEntry'))
                    return result

        result.append(node)
        i += 1
    return result


def extract_nodes(func, global_flags):
    parser = Parser(func.lines, global_flags, func)
    func.nodes = []
    for line in func.lines:
        m = RE_FLAG_SET.match(line)
        if m and m.group(1) in global_flags: func.flags_write.add(m.group(1))
        for flag in global_flags:
            if re.search(r'\b' + re.escape(flag) + r'\b', line) and '=' not in line.split(flag, 1)[0][-3:]:
                if re.search(r'\bnot\s+' + re.escape(flag) + r'\b', line) or re.search(r'\bif\(.*\b' + re.escape(flag) + r'\b', line):
                    func.flags_read.add(flag)
    while parser.peek() is not None:
        stmt = parser.parse_statement()
        if stmt is not None:
            if isinstance(stmt, list):
                func.nodes.extend(stmt)
            else:
                func.nodes.append(stmt)
    # Bug 2 post-pass: fold early-exit branches into else blocks
    func.nodes = fold_early_exits(func.nodes)

def parse_condition(cond_text, global_flags):
    cond = {"raw": cond_text}
    comparisons = RE_FLAG_COMPARE.findall(cond_text)
    compared_flags = set()
    flag_refs = []
    if comparisons:
        flag_ops = {}
        for flag_name, op, value in comparisons:
            if flag_name in global_flags:
                compared_flags.add(flag_name)
                flag_ops.setdefault((flag_name, op), []).append(value.rstrip('h'))
        for (flag_name, op), values in flag_ops.items():
            flag_refs.append({"flag": flag_name, "negated": False, "op": op, "values": values})
    for flag in global_flags:
        m_flag = re.search(r'\b' + re.escape(flag) + r'\b', cond_text)
        if m_flag and flag not in compared_flags:
            # Count 'not' keywords immediately preceding this flag reference.
            # fold now faithfully transcribes the condition (no synthetic 'not' added).
            # 'not flag'  (not_count=1) → NOT opcode present → negated=True  (fires when flag=0)
            # 'flag'      (not_count=0) → no NOT opcode    → negated=False (fires when flag≠0)
            prefix = cond_text[:m_flag.start()]
            m_trailing = re.search(r'(?:\bnot\b\s*)+$', prefix)
            not_count = len(re.findall(r'\bnot\b', m_trailing.group())) if m_trailing else 0
            flag_refs.append({"flag": flag, "negated": not_count >= 1})
    if flag_refs:
        cond["flags"] = flag_refs
        if len(flag_refs) >= 2:
            # fold uses ' or ' (with spaces) to join OR-combined flags; ' and ' for AND.
            # Detect from the raw condition text — safe because fold never uses 'or'/'and'
            # as part of a flag name (they are always surrounded by spaces as operators).
            cond["combinator"] = "or" if " or " in cond_text.lower() else "and"
    strcmp_matches = RE_STRCMP.findall(cond_text)
    if strcmp_matches: cond["strcmp"] = [{"var": v, "value": t} for v, t in strcmp_matches]
    m = RE_IS_DEAD.search(cond_text)
    if m:
        cond["isDead"] = m.group(1)
        # isDeadNegated=True: fold output has 'not isDead()' — NOT opcode before jne.
        # then-block fires when NOT(isDead())≠0 → isDead()=0 → NPC is ALIVE.
        # isDeadNegated=False: fold output has 'isDead()' — no NOT opcode.
        # then-block fires when isDead()≠0 → NPC is DEAD.
        prefix = cond_text[:m.start()].strip()
        cond["isDeadNegated"] = prefix.endswith('not')
    return cond

def iter_nodes(nodes):
    for n in nodes:
        if not isinstance(n, dict): continue
        yield n
        if n.get("type") in ("IfStatement", "ConversationLoop"):
            yield from iter_nodes(n.get("then", []))
            yield from iter_nodes(n.get("else", []))
            for elif_block in n.get("else_ifs", []): yield from iter_nodes(elif_block.get("body", []))
            yield from iter_nodes(n.get("body", []))

def rename_barks(nodes):
    for node in nodes:
        if not isinstance(node, dict): continue
        if node.get("type") == "Bark": node["type"] = "DialogueLine"
        if node.get("type") in ("IfStatement", "ConversationLoop"):
            rename_barks(node.get("then", []))
            rename_barks(node.get("else", []))
            for elif_block in node.get("else_ifs", []): rename_barks(elif_block.get("body", []))
            rename_barks(node.get("body", []))

def _parse_hex(s):
    """Parse a hex string like '0x0Ch' or '0x008Fh' to int."""
    s = s.strip().rstrip('h')
    if s.startswith('0x') or s.startswith('0X'):
        return int(s, 16)
    try: return int(s)
    except ValueError: return None

def extract_shop_items(func):
    """Walk a shop function's AST and extract structured item data.

    Pattern: an IfStatement with strcmp branches where each branch body contains
    SetFlag nodes that assign price/shape/frame to local variables, plus a
    DialogueLine describing the item.
    """
    items = []
    dismiss_phrases = {"nothing", "never mind", "no, ", "no thanks", "none", "goodbye",
                       "i cannot pay", "not right now", "not today", "nevermind",
                       "open a tab", "put it on my tab", "here is the amount",
                       "i will pay that", "aye"}

    def is_dismiss(text):
        lower = text.strip().lower().rstrip('. ')
        return (not lower or lower == "<empty_string>" or
                any(lower.startswith(p) for p in dismiss_phrases))

    def extract_from_strcmp_chain(node):
        """Extract items from the main strcmp IfStatement chain."""
        branches = []
        if node.get("condition", {}).get("strcmp"):
            branches.append((node["condition"]["strcmp"][0]["value"], node.get("then", [])))
        for eif in node.get("else_ifs", []):
            sc = eif.get("condition", {}).get("strcmp")
            if sc:
                branches.append((sc[0]["value"], eif.get("body", [])))

        for item_name, body_nodes in branches:
            name = item_name.strip()
            if is_dismiss(name):
                continue
            item = {"name": name}
            description_parts = []
            for bn in body_nodes:
                if bn.get("type") == "DialogueLine" and bn.get("text"):
                    description_parts.append(bn["text"].strip())
                if bn.get("type") == "SetFlag":
                    flag_name = bn.get("flag", "")
                    val = _parse_hex(bn.get("value", ""))
                    if val is not None:
                        item.setdefault("_setflags", []).append((flag_name, val))
            if description_parts:
                item["description"] = " ".join(description_parts)
            # Resolve price from collected SetFlags (kept in body order).
            setflags = item.pop("_setflags", [])
            if setflags:
                # If there's a named "cost" or "price" variable, use it directly.
                cost_flag = next((v for n, v in setflags if n.lower() in ("cost", "price")), None)
                if cost_flag is not None:
                    item["price"] = cost_flag
                else:
                    # Shape IDs are always > 128 (0x80).  The price is the first
                    # non-shape value set in body order (usecode always sets price
                    # before frame).
                    for _, v in setflags:
                        if 0 < v <= 128:
                            item["price"] = v
                            break
            items.append(item)

    def walk(nodes):
        for node in nodes:
            if node.get("type") == "IfStatement" and node.get("condition", {}).get("strcmp"):
                extract_from_strcmp_chain(node)
                return  # Only process the first item-selection chain
            if node.get("type") == "ConversationLoop":
                walk(node.get("body", []))
            for sub in ("then", "else", "body"):
                if node.get(sub):
                    walk(node[sub])
            for eif in node.get("else_ifs", []):
                walk(eif.get("body", []))

    walk(func.nodes)
    func.shop_items = items

def process_file(filepath, global_flags, item_data=None):
    with open(filepath, 'r', encoding='utf-8', errors='replace') as f: text = f.read()
    if not text.strip(): return None
    functions = parse_functions(text)
    if not functions: return None
    class_name = functions[0].class_name if functions else os.path.basename(filepath).replace('U8P_', '').replace('.txt', '')
    # Determine whether this class is an NPC.  An NPC class has at least one
    # function that calls beginConversation() — the U8 mechanism for entering
    # interactive dialogue.  Non-NPC objects (BOTTLE, FLASK, ABACUS, spell
    # scripts, etc.) never call beginConversation even if they emit barks.
    # This flag is used by classify_function to gate the 'monologue' type:
    # bark-only functions in object classes become 'utility' instead.
    is_npc_class = 'beginConversation()' in text
    for func in functions:
        classify_function(func, is_npc_class)
        extract_nodes(func, global_flags)
        func.variable_hints = infer_variable_hints(func)
        if func.classification in ("dialogue", "shop"): rename_barks(func.nodes)
        if func.classification == "shop": extract_shop_items(func)
    all_flags_read = set()
    all_flags_write = set()
    for func in functions:
        all_flags_read |= func.flags_read
        all_flags_write |= func.flags_write
    functions_dict = {}
    key_counts = {}
    for func in functions:
        base_key = EVENT_TYPES.get(func.process_type, func.name) if EVENT_TYPES.get(func.process_type, func.name) != func.name else func.name
        if base_key in key_counts:
            key_counts[base_key] += 1
            key = f"{base_key}_{key_counts[base_key]}"
        else:
            key_counts[base_key] = 0
            key = base_key
        functions_dict[key] = func.to_dict()
    all_nodes = [n for f in functions_dict.values() for n in iter_nodes(f.get("nodes", []))]
    result = {
        "npc": class_name,
        "sourceFile": os.path.basename(filepath),
        "functions": functions_dict,
        "flags": {"read": sorted(all_flags_read), "write": sorted(all_flags_write)},
        "stats": {
            "totalFunctions": len(functions_dict),
            "dialogueFunctions": sum(1 for f in functions_dict.values() if f.get("type") == "dialogue"),
            "lookFunctions": sum(1 for f in functions_dict.values() if f.get("type") == "look"),
            "monologueFunctions": sum(1 for f in functions_dict.values() if f.get("type") == "monologue"),
            "shopFunctions": sum(1 for f in functions_dict.values() if f.get("type") == "shop"),
            "behaviorFunctions": sum(1 for f in functions_dict.values() if f.get("type") == "behavior"),
            "utilityFunctions": sum(1 for f in functions_dict.values() if f.get("type") == "utility"),
            "totalNodes": len(all_nodes),
            "barkCount": sum(1 for n in all_nodes if n.get("type") == "Bark"),
            "dialogueLineCount": sum(1 for n in all_nodes if n.get("type") == "DialogueLine"),
            "askCount": sum(1 for n in all_nodes if n.get("type") == "Ask"),
            "strcmpBranches": sum(1 for n in all_nodes if n.get("type") == "IfStatement" and "strcmp" in n.get("condition", {})),
        },
        "hasDialogue": any(f.classification == "dialogue" for f in functions),
    }
    # Attach item properties (weapon/armour/overlay stats) when available
    if item_data:
        shape_to_weapon, shape_to_armour, class_to_shape, overlay_to_weapons = item_data
        item_props = build_item_properties(class_name, shape_to_weapon, shape_to_armour, class_to_shape, overlay_to_weapons)
        if item_props:
            result["itemProperties"] = item_props
    return result

def build_cross_references(input_dir):
    """Scan all fold files to find cross-class function calls.
    Returns {target_class: [{callerClass, callerFunc, targetFunc}, ...]}"""
    import collections
    RE_CROSS_CALL = re.compile(r'->(\w+)::(\w+)\(')
    RE_FUNC_DEF = re.compile(r'^(\w+)::(\w+)\(\)')
    xrefs = collections.defaultdict(list)
    files = sorted(f for f in os.listdir(input_dir) if f.startswith('U8P_') and f.endswith('.txt'))
    for filename in files:
        caller_class = filename.replace('U8P_', '').replace('.txt', '')
        current_func = None
        with open(os.path.join(input_dir, filename), 'r', encoding='latin-1') as fh:
            for raw_line in fh:
                line = raw_line.strip()
                # Function defs appear unindented: "CLASS::func()" at column 0
                if not raw_line[0:1].isspace() and not raw_line.startswith('=') and not raw_line.startswith('/'):
                    m_def = RE_FUNC_DEF.match(line)
                    if m_def and m_def.group(1) == caller_class:
                        current_func = m_def.group(2)
                        continue
                if not current_func:
                    continue
                for m in RE_CROSS_CALL.finditer(line):
                    target_class, target_func = m.group(1), m.group(2)
                    if target_class != caller_class and target_class not in ('FREE', 'METHOD', 'Item', 'Npc'):
                        xrefs[target_class].append({
                            'callerClass': caller_class,
                            'callerFunc': current_func,
                            'targetFunc': target_func,
                        })
    # Deduplicate
    deduped = {}
    for cls, refs in xrefs.items():
        seen = set()
        unique = []
        for r in refs:
            key = (r['callerClass'], r['callerFunc'], r['targetFunc'])
            if key not in seen:
                seen.add(key)
                unique.append(r)
        deduped[cls] = unique
    return deduped

def _resolve_repo_root(repo_root_arg):
    if repo_root_arg:
        return os.path.abspath(repo_root_arg)
    # .../titan-ultima/src/titan/dialogue/pipeline/extract_ast.py -> .../titan-ultima
    return str(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..')))


def _resolve_symbols_path(repo_root, symbols_arg):
    if symbols_arg:
        return symbols_arg
    candidates = [
        os.path.join(repo_root, 'src', 'titan', 'dialogue', 'reference', 'symbols.csv'),
        os.path.join(repo_root, '.github', 'reference', 'symbols.csv'),
    ]
    return next((p for p in candidates if os.path.isfile(p)), None)


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("input", nargs='?')
    parser.add_argument("--outdir", "-o", default=None)
    parser.add_argument("--symbols", "-s", default=None)
    parser.add_argument("--classes", default=None, help="Optional usecode_classes.csv path")
    parser.add_argument("--repo-root", default=None, help="Repository root used for optional reference/data lookups")
    parser.add_argument("--single", action="store_true")
    parser.add_argument("--dialogue-only", action="store_true")
    parser.add_argument("--stats", action="store_true")
    args = parser.parse_args(argv)

    repo_root = _resolve_repo_root(args.repo_root)
    symbols_path = _resolve_symbols_path(repo_root, args.symbols)
    global_flags = load_global_flags(symbols_path)
    item_data = load_item_data(repo_root, classes_csv=args.classes)
    input_dir = args.input if args.input and os.path.isdir(args.input) else (None if args.input else os.path.join(repo_root, 'foldExtract'))
    out_dir = args.outdir or os.path.join(repo_root, 'dialogue', 'json')

    if args.input and not os.path.exists(args.input):
        print(f"ERROR: Input path not found: {args.input}")
        return 1
    if not input_dir:
        print("ERROR: No input path provided and no default foldExtract directory was found.")
        return 1

    os.makedirs(out_dir, exist_ok=True)
    
    files = sorted(f for f in os.listdir(input_dir) if f.startswith('U8P_') and f.endswith('.txt')) if input_dir else [os.path.basename(args.input)]
    input_dir = input_dir or os.path.dirname(args.input)

    if not files:
        print(f"ERROR: No U8P_*.txt files found in {input_dir}")
        return 1

    cross_refs = build_cross_references(input_dir)
    
    results = []
    stats = {"total": 0, "empty": 0, "with_dialogue": 0, "with_barks": 0, "total_barks": 0, "total_dialogue_lines": 0, "total_asks": 0, "total_strcmp": 0, "total_flags_read": 0, "total_flags_write": 0}
    
    for filename in files:
        result = process_file(os.path.join(input_dir, filename), global_flags, item_data)
        stats["total"] += 1
        if result is None: stats["empty"] += 1; continue
        if args.dialogue_only and not result["hasDialogue"]: continue
        # Inject cross-references (who calls this class's functions)
        cls_name = result["npc"]
        if cls_name in cross_refs:
            result["calledFrom"] = cross_refs[cls_name]
        results.append(result)
        if result["hasDialogue"]: stats["with_dialogue"] += 1
        if result["stats"]["barkCount"] > 0 or result["stats"]["dialogueLineCount"] > 0: stats["with_barks"] += 1
        if not args.single:
            with open(os.path.join(out_dir, filename.replace('.txt', '.json')), 'w', encoding='utf-8') as f: json.dump(result, f, indent=2, ensure_ascii=False)

    if args.single:
        with open(os.path.join(out_dir, 'all_dialogue.json'), 'w', encoding='utf-8') as f: json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"Processed {len(results)} classes into {out_dir}")
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
