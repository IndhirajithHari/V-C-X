"""Native Verilog & SystemVerilog (.v, .sv) EDA Semantic Adapter for VCX.

Parses hardware description language (RTL) files using regex AST patterns to detect:
- Module declarations and parameter lists
- Input/output port interfaces and bit widths
- Procedural blocks (always_ff, always_comb, always_latch, always @)
- FSM state parameters and enumerated states
Outputs structured hardware hierarchy changes for the Semantic Differ Agent.
"""

from __future__ import annotations
from dataclasses import dataclass, field
import re
from typing import Any, Dict, List, Optional, Set, Tuple


@dataclass
class PortInfo:
    direction: str  # input, output, inout
    name: str
    width: str = ""  # e.g. "[7:0]" or ""
    data_type: str = ""  # wire, reg, logic, or ""

    def to_dict(self) -> Dict[str, str]:
        return {
            "direction": self.direction,
            "name": self.name,
            "width": self.width,
            "data_type": self.data_type,
        }


@dataclass
class ModuleInfo:
    name: str
    ports: Dict[str, PortInfo] = field(default_factory=dict)
    parameters: Dict[str, str] = field(default_factory=dict)
    fsm_states: List[str] = field(default_factory=list)
    procedural_blocks: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "ports": {k: v.to_dict() for k, v in self.ports.items()},
            "parameters": self.parameters,
            "fsm_states": self.fsm_states,
            "procedural_blocks": self.procedural_blocks,
        }


class EDAAdapter:
    """Extracts RTL architecture, port declarations, and FSM changes from Verilog/SystemVerilog."""

    # Regex patterns for Verilog / SystemVerilog AST parsing
    MODULE_RE = re.compile(
        r"\bmodule\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?:#\s*\((.*?)\))?\s*(?:\((.*?)\))?;",
        re.DOTALL,
    )
    PORT_RE = re.compile(
        r"\b(input|output|inout)\s+(?:(reg|wire|logic)\s+)?(?:(\[[^\]]+\])\s+)?([A-Za-z_][A-Za-z0-9_]*)",
        re.MULTILINE,
    )
    PARAM_RE = re.compile(
        r"\b(?:parameter|localparam)\s+(?:(?:reg|wire|logic|integer|bit)\s+)?(?:(\[[^\]]+\])\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([^;,]+)",
        re.MULTILINE,
    )
    ENUM_RE = re.compile(
        r"\btypedef\s+enum\s+(?:logic|bit)?\s*(?:\[[^\]]+\])?\s*\{(.*?)\}\s*([A-Za-z_][A-Za-z0-9_]*);",
        re.DOTALL,
    )
    PROC_BLOCK_RE = re.compile(
        r"\b(always_ff|always_comb|always_latch|always\s*@\s*\(.*?\)|initial)\b",
        re.DOTALL,
    )

    @classmethod
    def parse_verilog(cls, text: Union[str, bytes]) -> Dict[str, ModuleInfo]:
        """Parse Verilog/SystemVerilog code into a dictionary of module definitions."""
        if isinstance(text, bytes):
            try:
                text = text.decode("utf-8", errors="replace")
            except Exception:
                text = text.decode("latin-1", errors="replace")
        if not text:
            return {}

        # Clean null bytes if present
        text = text.replace("\x00", "")

        # Strip line comments (//) and block comments (/* */)
        cleaned = re.sub(r"//.*$", "", text, flags=re.MULTILINE)
        cleaned = re.sub(r"/\*.*?\*/", "", cleaned, flags=re.DOTALL)

        modules: Dict[str, ModuleInfo] = {}

        # Split modules
        module_blocks = re.findall(r"\bmodule\s+([A-Za-z_][A-Za-z0-9_]*).*?\bendmodule\b", cleaned, re.DOTALL)
        # Find raw spans of modules
        mod_iter = re.finditer(r"\bmodule\s+([A-Za-z_][A-Za-z0-9_]*)(.*?)\bendmodule\b", cleaned, re.DOTALL)

        for match in mod_iter:
            mod_name = match.group(1)
            body = match.group(2)

            mod_info = ModuleInfo(name=mod_name)

            # 1. Extract Ports (ANSI header and body declarations)
            for p_match in cls.PORT_RE.finditer(body):
                direction = p_match.group(1)
                dtype = p_match.group(2) or ""
                width = (p_match.group(3) or "").strip()
                p_name = p_match.group(4)
                mod_info.ports[p_name] = PortInfo(
                    direction=direction,
                    name=p_name,
                    width=width,
                    data_type=dtype,
                )

            # 2. Extract Parameters
            for param_match in cls.PARAM_RE.finditer(body):
                p_width = param_match.group(1) or ""
                p_name = param_match.group(2)
                p_val = param_match.group(3).strip()
                mod_info.parameters[p_name] = p_val
                # Check if looks like FSM state
                if any(k in p_name.upper() for k in ("STATE", "S_", "ST_", "IDLE", "WAIT", "EXEC", "DONE")):
                    mod_info.fsm_states.append(f"{p_name}={p_val}")

            # 3. Extract SystemVerilog Enums (FSMs)
            for enum_match in cls.ENUM_RE.finditer(body):
                states_str = enum_match.group(1)
                for s in states_str.split(","):
                    s_clean = s.strip()
                    if s_clean:
                        mod_info.fsm_states.append(s_clean)

            # 4. Extract Procedural Blocks
            for pb in cls.PROC_BLOCK_RE.finditer(body):
                block_desc = pb.group(1).replace("\n", " ")
                block_desc = re.sub(r"\s+", " ", block_desc).strip()
                mod_info.procedural_blocks.append(block_desc)

            modules[mod_name] = mod_info

        return modules

    @classmethod
    def diff(
        cls,
        base_data: Optional[Union[bytes, str]],
        current_data: Union[bytes, str],
        file_name: str = "design.v",
    ) -> Dict[str, Any]:
        """Perform hardware-aware semantic diff comparing two Verilog states."""
        if isinstance(base_data, str):
            base_text = base_data
        elif base_data is not None:
            try:
                base_text = base_data.decode("utf-8", errors="replace")
            except Exception:
                base_text = base_data.decode("latin-1", errors="replace")
        else:
            base_text = ""

        if isinstance(current_data, str):
            curr_text = current_data
        elif current_data is not None:
            try:
                curr_text = current_data.decode("utf-8", errors="replace")
            except Exception:
                curr_text = current_data.decode("latin-1", errors="replace")
        else:
            curr_text = ""

        base_mods = cls.parse_verilog(base_text)
        curr_mods = cls.parse_verilog(curr_text)

        modules_added: List[str] = []
        modules_removed: List[str] = []
        port_changes: List[Dict[str, Any]] = []
        fsm_changes: List[str] = []
        procedural_changes: List[str] = []
        bullets: List[str] = []

        all_mod_names = set(base_mods.keys()) | set(curr_mods.keys())

        for m_name in sorted(all_mod_names):
            if m_name not in base_mods:
                modules_added.append(m_name)
                bullets.append(f"Declared new hardware module: {m_name}")
                curr_p = curr_mods[m_name].ports
                if curr_p:
                    bullets.append(f"  * Ports ({len(curr_p)}): {', '.join(curr_p.keys())}")
            elif m_name not in curr_mods:
                modules_removed.append(m_name)
                bullets.append(f"Removed hardware module: {m_name}")
            else:
                b_mod = base_mods[m_name]
                c_mod = curr_mods[m_name]

                # Check ports
                b_ports = b_mod.ports
                c_ports = c_mod.ports

                for p_name, c_port in c_ports.items():
                    if p_name not in b_ports:
                        bullets.append(
                            f"Module '{m_name}': Added {c_port.direction} port '{p_name}' {c_port.width}".strip()
                        )
                        port_changes.append({
                            "module": m_name,
                            "type": "added",
                            "name": p_name,
                            "port": p_name,
                            "direction": c_port.direction,
                            "width": c_port.width,
                        })
                    else:
                        b_port = b_ports[p_name]
                        if b_port.width != c_port.width or b_port.direction != c_port.direction:
                            bullets.append(
                                f"Module '{m_name}': Modified port '{p_name}' ({b_port.direction} {b_port.width} -> {c_port.direction} {c_port.width})".strip()
                            )
                            port_changes.append({
                                "module": m_name,
                                "type": "modified",
                                "name": p_name,
                                "port": p_name,
                                "old": f"{b_port.direction} {b_port.width}".strip(),
                                "new": f"{c_port.direction} {c_port.width}".strip(),
                            })

                for p_name, b_port in b_ports.items():
                    if p_name not in c_ports:
                        bullets.append(f"Module '{m_name}': Removed {b_port.direction} port '{p_name}'")
                        port_changes.append({
                            "module": m_name,
                            "type": "removed",
                            "name": p_name,
                            "port": p_name,
                        })

                # Check FSM States
                b_fsm = set(b_mod.fsm_states)
                c_fsm = set(c_mod.fsm_states)
                if b_fsm != c_fsm:
                    added_states = c_fsm - b_fsm
                    removed_states = b_fsm - c_fsm
                    if added_states:
                        msg = f"Module '{m_name}': Added FSM states: {', '.join(sorted(added_states))}"
                        fsm_changes.append(msg)
                        bullets.append(msg)
                    if removed_states:
                        msg = f"Module '{m_name}': Removed FSM states: {', '.join(sorted(removed_states))}"
                        fsm_changes.append(msg)
                        bullets.append(msg)

                # Check procedural blocks count / types
                if len(b_mod.procedural_blocks) != len(c_mod.procedural_blocks):
                    delta = len(c_mod.procedural_blocks) - len(b_mod.procedural_blocks)
                    verb = "Added" if delta > 0 else "Removed"
                    msg = f"Module '{m_name}': {verb} {abs(delta)} procedural block(s) (always/always_ff)"
                    procedural_changes.append(msg)
                    bullets.append(msg)

        has_changes = bool(modules_added or modules_removed or port_changes or fsm_changes or procedural_changes)

        summary = (
            f"Hardware architecture updates in {file_name}: "
            + f"{len(modules_added)} modules added, {len(port_changes)} port interface modifications, {len(fsm_changes)} FSM changes"
            if has_changes
            else f"No structural hardware interface changes in {file_name}"
        )

        return {
            "format": "Verilog/EDA",
            "file": file_name,
            "has_changes": has_changes,
            "modules_added": modules_added,
            "modules_removed": modules_removed,
            "port_changes": port_changes,
            "fsm_changes": fsm_changes,
            "procedural_changes": procedural_changes,
            "technical_bullets": bullets,
            "summary": summary,
        }
