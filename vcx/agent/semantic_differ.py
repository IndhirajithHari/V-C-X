"""Core Semantic Differ Agent for VCX.

Operates autonomously in the background to analyze changes between two BLOB states
and generate precise, human-readable commit messages, technical deltas, and intent.
"""

from __future__ import annotations
import json
import os
import re
from typing import Any, Dict, List, Optional

from vcx.agent.prompt import SYSTEM_PROMPT
from vcx.agent.schemas import DifferInput, DifferOutput


class SemanticDifferAgent:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")

    def analyze(self, input_data: DifferInput | Dict[str, Any]) -> DifferOutput:
        """Analyze changes and produce strictly schema-compliant output."""
        if isinstance(input_data, dict):
            payload = DifferInput.from_dict(input_data)
        else:
            payload = input_data

        # Try LLM if API key is configured
        if self.api_key:
            llm_result = self._call_llm(payload)
            if llm_result:
                return llm_result

        # Autonomous Embedded Deterministic Differ Engine
        return self._embedded_semantic_analysis(payload)

    def _call_llm(self, payload: DifferInput) -> Optional[DifferOutput]:
        try:
            import urllib.request

            url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
            payload_dict = payload.to_dict()
            # Bounded token window guard: truncate oversized diffs for LLM prompt
            if payload_dict.get("raw_diff") and len(payload_dict["raw_diff"]) > 10000:
                payload_dict["raw_diff"] = payload_dict["raw_diff"][:10000] + "\n... [diff truncated]"

            prompt_content = (
                f"{SYSTEM_PROMPT}\n\n"
                f"Analyze the following change payload:\n"
                f"{json.dumps(payload_dict, indent=2)}"
            )
            req_body = json.dumps(
                {
                    "contents": [{"parts": [{"text": prompt_content}]}],
                    "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"},
                }
            ).encode("utf-8")

            req = urllib.request.Request(
                url,
                data=req_body,
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": self.api_key,
                },
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))
                text = res_data["candidates"][0]["content"]["parts"][0]["text"].strip()
                # Strip any accidental markdown formatting
                if text.startswith("```json"):
                    text = text[7:]
                if text.startswith("```"):
                    text = text[3:]
                if text.endswith("```"):
                    text = text[:-3]
                parsed = json.loads(text.strip())
                return DifferOutput.from_dict(parsed)
        except Exception:
            return None

    def _embedded_semantic_analysis(self, payload: DifferInput) -> DifferOutput:
        """Deterministic context-aware semantic analysis adhering to all operating rules."""
        file_name = payload.file_name
        file_type = payload.file_type
        raw_diff = payload.raw_diff or ""
        prev_meta = payload.previous_metadata or {}
        curr_meta = payload.current_metadata or {}
        vision_summary = payload.vision_summary or ""
        facts = payload.domain_facts or {}

        # 0. CUSTOM PLUGINS
        if file_type == "plugin/custom":
            return self._analyze_plugin_change(file_name, file_type, raw_diff, prev_meta, curr_meta, facts)

        # 1. MUSIC DAWS & AUDIO PRODUCTION (Ableton, Reaper, FL Studio)
        if file_type.startswith("music/"):
            return self._analyze_music_change(file_name, file_type, raw_diff, prev_meta, curr_meta, facts)

        # 2. GAME ENGINES & INTERACTIVE 3D (Unity, Godot, Unreal)
        if file_type.startswith("game/"):
            return self._analyze_game_change(file_name, file_type, raw_diff, prev_meta, curr_meta, facts)

        # 3. DESIGN, UI/UX & DIGITAL ART (Sketch, Krita, GIMP, Figma)
        if file_type.startswith("design/"):
            return self._analyze_design_change(file_name, file_type, raw_diff, prev_meta, curr_meta, facts)

        # 4. BIG DATA & SCIENTIFIC (Parquet, HDF5)
        if file_type.startswith("scientific/") or file_type == "database/parquet":
            return self._analyze_scientific_change(file_name, file_type, raw_diff, prev_meta, curr_meta, facts)

        # 5. HARDWARE / EDA (Verilog, SystemVerilog, KiCad, JSON Floorplans)
        if file_type.startswith("eda/"):
            return self._analyze_hardware_change(
                file_name, file_type, raw_diff, prev_meta, curr_meta, facts
            )

        # 6. CAD / 3D MODELS (FreeCAD, DXF, DWG, STL, STEP)
        if file_type.startswith("cad/"):
            return self._analyze_cad_change(
                file_name, file_type, raw_diff, prev_meta, curr_meta, vision_summary, facts
            )

        # 7. DATABASES / LOGS (SQLite, CSV)
        if file_type.startswith("database/") or file_type.startswith("log/"):
            return self._analyze_database_change(
                file_name, file_type, raw_diff, prev_meta, curr_meta
            )

        # 8. MULTIMEDIA (Video, Audio, Images)
        if file_type.startswith("video/") or file_type.startswith("audio/") or file_type.startswith("image/"):
            return self._analyze_media_change(
                file_name, file_type, raw_diff, prev_meta, curr_meta, vision_summary
            )

        # 9. CREATIVE APPS & PROJECTS (Premiere, Resolve, Photoshop, Blender, Office)
        if file_type.startswith("creative/") or file_type.startswith("document/") or file_type.startswith("archive/"):
            return self._analyze_creative_change(
                file_name, file_type, raw_diff, prev_meta, curr_meta, vision_summary
            )

        # 10. SOURCE CODE (Python, Rust, C, C++)
        if file_type.startswith("source/"):
            return self._analyze_code_change(
                file_name, file_type, raw_diff, prev_meta, curr_meta
            )

        # 11. UNIVERSAL BINARY / CDC / UNKNOWN (File-system level factual analysis)
        return self._analyze_binary_change(
            file_name, file_type, raw_diff, prev_meta, curr_meta, facts
        )

    def _analyze_hardware_change(
        self,
        file_name: str,
        file_type: str,
        raw_diff: str,
        prev_meta: Any,
        curr_meta: Any,
        facts: Optional[Dict[str, Any]] = None,
    ) -> DifferOutput:
        delta_points: List[str] = []
        tags = ["eda-hardware"]
        mod_name = file_name.split(".")[0]

        if file_type in ("eda/kicad", "eda/eagle"):
            tags.extend(["kicad", "pcb-layout"])
            nets = (facts or {}).get("nets_count", 0)
            fps = (facts or {}).get("footprints_count", 0)
            layers = (facts or {}).get("layers_count", 0)
            delta_points.append(f"KiCad PCB layout: {fps} footprints, {nets} electrical nets, {layers} layers")
            action = f"Update KiCad PCB layout {file_name}"[:49]
            intent = "Update schematic netlist routing and board component placement."
            return DifferOutput(action, delta_points, intent, tags)

        # Check for ALU / Pipeline changes
        is_alu = bool(re.search(r"alu|arithmetic|logic|pipeline|stage", file_name, re.I))
        is_riscv = bool(re.search(r"riscv|rv32|rv64|isa|opcode", file_name + raw_diff, re.I))

        if is_riscv:
            tags.append("risc-v")
        if is_alu:
            tags.append("pipeline")

        # Floorplan
        if "floorplan" in file_type or "floorplan" in file_name.lower():
            tags.append("floorplan")
            moved = []
            if isinstance(curr_meta, dict) and isinstance(prev_meta, dict):
                curr_macros = curr_meta.get("macros", {})
                prev_macros = prev_meta.get("macros", {})
                for k, v in curr_macros.items():
                    if k in prev_macros and v != prev_macros[k]:
                        moved.append(f"{k} moved to ({v.get('x')}, {v.get('y')})")
            if moved:
                delta_points.extend(moved)
                action = f"Relocate macros in {file_name}"[:49]
                intent = "Optimize routing wirelength and core cell utilization."
            else:
                delta_points.append("Adjust macro placement coordinates and routing track alignment")
                action = f"Update floorplan layout for {file_name}"[:49]
                intent = "Address timing violations and minimize parasitic capacitance."
            return DifferOutput(action, delta_points, intent, tags)

        # HDL Code / Verilog / SystemVerilog
        # Check domain facts from EDAAdapter first
        facts_dict = facts or {}
        port_changes = facts_dict.get("port_changes", [])
        fsm_changes = facts_dict.get("fsm_changes", [])
        modules_added = facts_dict.get("modules_added", [])
        modules_removed = facts_dict.get("modules_removed", [])

        for m in modules_added:
            delta_points.append(f"Declared new hardware module: {m}")
        for m in modules_removed:
            delta_points.append(f"Removed hardware module: {m}")

        for pc in port_changes:
            if isinstance(pc, dict):
                p_type = pc.get("type", "modified")
                p_name = pc.get("port", "unknown")
                m_name = pc.get("module", mod_name)
                if p_type == "added":
                    dir_w = f"{pc.get('direction', '')} {pc.get('width', '')}".strip()
                    delta_points.append(f"Module '{m_name}': Added {dir_w} port '{p_name}'".strip())
                elif p_type == "modified":
                    old_val = pc.get("old", "")
                    new_val = pc.get("new", "")
                    delta_points.append(f"Module '{m_name}': Modified port '{p_name}' ({old_val} -> {new_val})".strip())
                elif p_type == "removed":
                    delta_points.append(f"Module '{m_name}': Removed port '{p_name}'")
            elif isinstance(pc, str):
                delta_points.append(pc)

        for fsm in fsm_changes:
            delta_points.append(fsm if isinstance(fsm, str) else str(fsm))

        # Textual diff heuristics
        if "always" in raw_diff or "posedge" in raw_diff:
            delta_points.append("Modified sequential always @(posedge clk) control logic")
        if "case" in raw_diff or "opcode" in raw_diff.lower():
            delta_points.append("Updated instruction decode case branch mappings")
        if "reg" in raw_diff or "wire" in raw_diff:
            if not port_changes:
                delta_points.append("Updated internal datapath register and signal declarations")

        if not delta_points:
            delta_points.append(f"Refactored {mod_name} module logic and port mappings")

        # Dynamic Action Summary & Intent
        if is_alu and is_riscv:
            action = "Update RISC-V ALU pipeline logic"
            intent = "Improve ALU execution stage throughput and instruction decode timing."
        elif is_alu:
            action = f"Update ALU pipeline logic in {mod_name}"[:49]
            intent = "Enhance execution datapath and critical path timing margins."
        elif port_changes:
            action = f"Update {mod_name} port interface"[:49]
            intent = "Align hardware description with updated register transfer specifications."
        elif modules_added:
            action = f"Add module {modules_added[0]}"[:49]
            intent = "Align hardware description with updated register transfer specifications."
        else:
            action = f"Refactor {mod_name} hardware module"[:49]
            intent = "Align hardware description with updated register transfer specifications."

        return DifferOutput(action, delta_points, intent, tags)

    def _analyze_cad_change(
        self,
        file_name: str,
        file_type: str,
        raw_diff: str,
        prev_meta: Any,
        curr_meta: Any,
        vision_summary: str,
        facts: Optional[Dict[str, Any]] = None,
    ) -> DifferOutput:
        delta_points: List[str] = []
        tags = ["cad-geometry"]

        # Fillet / Extrusion / Dimension matching from diff or metadata
        fillet_match = re.search(r"fillet.*?([0-9.]+)\s*mm", raw_diff + vision_summary, re.I)
        extrusion_match = re.search(r"(?:extrusion|pad|thickness).*?([0-9.]+)\s*mm", raw_diff + vision_summary, re.I)

        if file_type == "cad/freecad":
            tags.extend(["freecad", "parametric-cad"])
            facts_dict = facts or {}
            props = facts_dict.get("properties_modified", [])
            added = facts_dict.get("objects_added", [])
            removed = facts_dict.get("objects_removed", [])
            sketches = facts_dict.get("sketch_changes", [])

            for p in props:
                delta_points.append(f"Modified {p['object']}.{p['property']}: {p['old_value']} -> {p['new_value']}")
            for a in added:
                name = a.get("name", "Unknown") if isinstance(a, dict) else str(a)
                otype = a.get("type", "Feature") if isinstance(a, dict) else "Feature"
                delta_points.append(f"Added CAD feature: {name} [{otype}]")
            for r in removed:
                name = r.get("name", "Unknown") if isinstance(r, dict) else str(r)
                delta_points.append(f"Removed CAD feature: {name}")
            for s in sketches:
                delta_points.append(s if isinstance(s, str) else str(s))

            if not delta_points:
                if fillet_match:
                    r = fillet_match.group(1)
                    delta_points.append(f"Added {r}mm fillet to edge geometry")
                    action = f"Add {r}mm fillet to chassis edge"[:49]
                    tags.append("fillet")
                elif extrusion_match:
                    t = extrusion_match.group(1)
                    delta_points.append(f"Increased base extrusion thickness by {t}mm")
                    action = f"Increase base extrusion thickness by {t}mm"[:49]
                    tags.append("extrusion")
                else:
                    objs = facts_dict.get("objects_count") or (curr_meta or {}).get("features_count", 0)
                    if objs:
                        delta_points.append(f"FreeCAD model: {objs} geometric features & bodies")
                    else:
                        delta_points.append(f"Updated FreeCAD model {file_name}")

            if "action" not in locals():
                if props:
                    action = f"Update {props[0]['object']}.{props[0]['property']}"[:49]
                elif added:
                    feat_name = added[0].get("name", "feature") if isinstance(added[0], dict) else str(added[0])
                    action = f"Add {feat_name} to {file_name}"[:49]
                elif removed:
                    feat_name = removed[0].get("name", "feature") if isinstance(removed[0], dict) else str(removed[0])
                    action = f"Remove {feat_name} from {file_name}"[:49]
                else:
                    action = f"Update FreeCAD model {file_name}"[:49]

            intent = "Update parametric 3D body tree and sketch constraints."
            return DifferOutput(action, delta_points, intent, tags)
        elif fillet_match:
            r = fillet_match.group(1)
            delta_points.append(f"Added {r}mm fillet to edge geometry")
            action = f"Add {r}mm fillet to chassis edge"[:49]
            tags.append("fillet")
        elif extrusion_match:
            t = extrusion_match.group(1)
            delta_points.append(f"Increased base extrusion thickness by {t}mm")
            action = f"Increase base extrusion thickness by {t}mm"[:49]
            tags.append("extrusion")
        elif file_type in ("cad/dwg", "cad/dxf"):
            tags.extend(["autocad", "vector-cad"])
            ents = (facts or {}).get("entities_count", 0)
            layers = len((facts or {}).get("layers", []))
            delta_points.append(f"AutoCAD drawing: {ents} entities across {layers} layers")
            action = f"Update CAD drawing {file_name}"[:49]
            intent = "Update 2D/3D drafting entities and layer geometries."
            return DifferOutput(action, delta_points, intent, tags)
        else:
            # Check mesh stats
            if isinstance(curr_meta, dict) and "mesh_stats" in curr_meta:
                n_mesh = curr_meta["mesh_stats"]
                o_mesh = prev_meta.get("mesh_stats", {}) if isinstance(prev_meta, dict) else {}
                v_diff = n_mesh.get("vertices", 0) - o_mesh.get("vertices", 0)
                if v_diff != 0:
                    delta_points.append(f"Updated mesh topology (vertex delta: {v_diff:+d})")
                if "bounding_box_mm" in n_mesh:
                    delta_points.append(f"Adjusted bounding box to {n_mesh['bounding_box_mm']}mm")
            if not delta_points:
                delta_points.append("Updated parametric model dimensions and topological features")
            action = f"Update {file_name} model geometry"[:49]

        if vision_summary:
            delta_points.append(f"Viewport analysis: {vision_summary}")

        intent = "Fulfill mechanical packaging tolerances and structural load requirements."
        return DifferOutput(action, delta_points, intent, tags)

    def _analyze_database_change(
        self,
        file_name: str,
        file_type: str,
        raw_diff: str,
        prev_meta: Any,
        curr_meta: Any,
    ) -> DifferOutput:
        delta_points: List[str] = []
        tags = ["database"]

        if file_type == "database/sqlite":
            tags.append("sqlite")
            row_changes = []
            if isinstance(curr_meta, dict) and isinstance(prev_meta, dict):
                for table, n_data in curr_meta.items():
                    o_data = prev_meta.get(table, {"count": 0})
                    diff = n_data.get("count", 0) - o_data.get("count", 0)
                    if diff != 0:
                        row_changes.append((table, diff))

            if row_changes:
                t_name, count = row_changes[0]
                if count > 0:
                    delta_points.append(f"Appended {count} new rows to '{t_name}'")
                    action = f"Append {count} new rows to {t_name}"[:49]
                else:
                    delta_points.append(f"Pruned {abs(count)} rows from '{t_name}'")
                    action = f"Prune {abs(count)} rows from {t_name}"[:49]
                intent = "Record new transactional state and persistent history."
            else:
                delta_points.append("Modified database schema / indexes")
                action = f"Update schema in {file_name}"[:49]
                intent = "Apply database migrations and optimize lookup indexing."
        else:  # CSV / Logs
            tags.append("logs")
            count = 0
            if isinstance(curr_meta, dict) and isinstance(prev_meta, dict):
                c_rows = curr_meta.get("total_rows")
                p_rows = prev_meta.get("total_rows")
                if c_rows is not None and p_rows is not None:
                    count = c_rows - p_rows

            if count <= 0:
                m = re.search(r"\+\s*(\d+)\s+rows", raw_diff, re.I)
                if m:
                    count = int(m.group(1))
                else:
                    lines_added = len([l for l in raw_diff.splitlines() if l.startswith("+") and not l.startswith("+++")])
                    count = max(lines_added, 1)

            count = max(count, 1)

            if "trade" in file_name.lower():
                action = f"Append {count} new trade execution logs"[:49]
                delta_points.append(f"Appended {count} new trade execution logs")
                intent = "Persist executed market orders and audit trail."
            else:
                action = f"Append {count} new log records"[:49]
                delta_points.append(f"Appended {count} new structured log entries to {file_name}")
                intent = "Synchronize execution event logs."

        return DifferOutput(action, delta_points, intent, tags)

    def _analyze_code_change(
        self,
        file_name: str,
        file_type: str,
        raw_diff: str,
        prev_meta: Any,
        curr_meta: Any,
    ) -> DifferOutput:
        delta_points: List[str] = []
        lang = file_type.split("/")[-1]
        tags = ["source-code", lang]

        # Check for memory leaks or scheduler allocation
        is_scheduler = bool(re.search(r"sched|alloc|task|queue", file_name + raw_diff, re.I))
        is_memory = bool(re.search(r"free|malloc|leak|box|arc|mutex|drop|cleanup", raw_diff, re.I))

        # Check functions
        old_fns = set(prev_meta.get("functions", {}).keys()) if isinstance(prev_meta, dict) else set()
        new_fns = set(curr_meta.get("functions", {}).keys()) if isinstance(curr_meta, dict) else set()

        added_fns = new_fns - old_fns
        removed_fns = old_fns - new_fns

        if added_fns:
            fn_list = ", ".join(sorted(list(added_fns))[:2])
            delta_points.append(f"Implemented new function(s): {fn_list}")
        if removed_fns:
            fn_list = ", ".join(sorted(list(removed_fns))[:2])
            delta_points.append(f"Removed deprecated function(s): {fn_list}")

        # Check memory / control flow
        if is_memory and is_scheduler:
            action = "Refactor scheduler allocation logic"[:49]
            delta_points.append("Updated resource cleanup and lock handling during task dequeue")
            intent = "Prevent memory leaks and eliminate lock contention in worker threads."
            tags.extend(["memory-management", "scheduler"])
        elif is_memory:
            action = f"Fix memory management in {file_name}"[:49]
            delta_points.append("Added proper deallocation and pointer lifecycle management")
            intent = "Eliminate potential memory leaks and dangling pointer references."
            tags.append("memory-management")
        elif added_fns:
            action = f"Add {list(added_fns)[0]} in {file_name}"[:49]
            delta_points.append("Extended module interface with new entry point logic")
            intent = "Provide necessary application functionality per architectural roadmap."
            tags.append("feature")
        else:
            action = f"Refactor logic in {file_name}"[:49]
            delta_points.append("Refactored internal control flow and error propagation")
            intent = "Improve code maintainability, error handling, and runtime robustness."
            tags.append("refactor")

        return DifferOutput(action, delta_points, intent, tags)

    def _analyze_binary_change(
        self,
        file_name: str,
        file_type: str,
        raw_diff: str,
        prev_meta: Any,
        curr_meta: Any,
        facts: Optional[Dict[str, Any]] = None,
    ) -> DifferOutput:
        delta_points: List[str] = []
        tags = ["binary", "file-system"]

        old_size = prev_meta.get("size_bytes", 0) if isinstance(prev_meta, dict) else 0
        new_size = curr_meta.get("size_bytes", 0) if isinstance(curr_meta, dict) else 0
        delta = new_size - old_size

        if abs(delta) >= 1024 * 1024:
            mb = abs(delta) / (1024 * 1024)
            verb = "increased" if delta > 0 else "decreased"
            size_msg = f"File size {verb} by {mb:.0f}MB"
        elif abs(delta) >= 1024:
            kb = abs(delta) / 1024
            verb = "increased" if delta > 0 else "decreased"
            size_msg = f"File size {verb} by {kb:.0f}KB"
        else:
            verb = "increased" if delta >= 0 else "decreased"
            size_msg = f"File size {verb} by {abs(delta)} bytes"

        delta_points.append(size_msg)

        facts = facts or {}
        mutation = facts.get("mutation_percentage")
        similarity = facts.get("similarity_ratio")
        added_strings = facts.get("added_strings", [])
        sig = facts.get("format_signature")

        if sig and sig not in ("Generic Binary", "Empty"):
            tags.append(sig.split()[0].lower())
            delta_points.append(f"Format signature: {sig}")

        if mutation is not None and similarity is not None:
            delta_points.append(f"Binary mutation: {mutation:.1f}% changed (similarity: {similarity:.1%})")

        if added_strings:
            delta_points.append(f"Extracted symbols: {', '.join(added_strings[:3])}")

        if isinstance(curr_meta, dict) and "entropy" in curr_meta:
            delta_points.append(f"Recorded binary entropy at {curr_meta['entropy']:.2f}")

        if mutation is not None and mutation > 0:
            action = f"Update {file_name} ({mutation:.1f}% mutated)"
        else:
            action = f"Update {file_name} ({size_msg})"
        if len(action) >= 50:
            short_msg = f"+{mb:.0f}MB" if abs(delta) >= 1024 * 1024 else f"{delta:+d}B"
            action = f"Update {file_name} ({short_msg})"
        if len(action) >= 50:
            action = f"Update {file_name} binary"[:49]

        intent = "Update compiled artifact, asset blocks, and binary data."
        return DifferOutput(action, delta_points, intent, tags)

    def _analyze_plugin_change(
        self,
        file_name: str,
        file_type: str,
        raw_diff: str,
        prev_meta: Any,
        curr_meta: Any,
        facts: Optional[Dict[str, Any]] = None,
    ) -> DifferOutput:
        delta_points: List[str] = []
        tags = ["plugin", "custom-adapter"]
        first_line = raw_diff.splitlines()[0] if raw_diff else f"Updated {file_name}"
        delta_points.append(first_line[:80])
        action = f"Update {file_name} via plugin"[:49]
        intent = "Apply external application adapter transformation."
        return DifferOutput(action, delta_points, intent, tags)

    def _analyze_music_change(
        self,
        file_name: str,
        file_type: str,
        raw_diff: str,
        prev_meta: Any,
        curr_meta: Any,
        facts: Optional[Dict[str, Any]] = None,
    ) -> DifferOutput:
        delta_points: List[str] = []
        tags = ["music-production", "daw"]
        facts = facts or {}
        daw = facts.get("daw", "DAW")
        bpm = facts.get("tempo_bpm") or facts.get("bpm")
        tracks = facts.get("tracks_count", 0)
        track_names = facts.get("track_names", [])

        if "ableton" in file_type or daw == "Ableton Live":
            tags.extend(["ableton-live", "electronic-music"])
            action = f"Update Ableton Live project {file_name}"[:49]
            intent = "Refine electronic arrangement, stems, and MIDI clips."
        elif "reaper" in file_type or daw == "Cockos Reaper":
            tags.extend(["reaper", "multitrack"])
            action = f"Update Reaper session {file_name}"[:49]
            intent = "Update audio stems, markers, and plugin routings."
        else:
            tags.append("audio-composition")
            action = f"Update DAW project {file_name}"[:49]
            intent = "Adjust musical arrangement and audio track stems."

        if bpm:
            delta_points.append(f"Project tempo: {bpm} BPM")
        if tracks:
            delta_points.append(f"Session tracks: {tracks} active tracks")
        if track_names:
            delta_points.append(f"Arrangement stems: {', '.join(track_names[:3])}")
        if not delta_points:
            delta_points.append(f"Updated music composition in {file_name}")

        return DifferOutput(action, delta_points, intent, tags)

    def _analyze_game_change(
        self,
        file_name: str,
        file_type: str,
        raw_diff: str,
        prev_meta: Any,
        curr_meta: Any,
        facts: Optional[Dict[str, Any]] = None,
    ) -> DifferOutput:
        delta_points: List[str] = []
        tags = ["game-development", "interactive-3d"]
        facts = facts or {}
        engine = facts.get("engine", "Game Engine")

        if "unity" in file_type or engine == "Unity":
            tags.extend(["unity", "scene-graph"])
            action = f"Update Unity scene {file_name}"[:49]
            gos = facts.get("game_objects_count", 0)
            comps = facts.get("components_count", 0)
            if gos or comps:
                delta_points.append(f"Unity hierarchy: {gos} GameObjects, {comps} Components")
            if facts.get("object_names"):
                delta_points.append(f"Entities: {', '.join(facts['object_names'][:3])}")
            intent = "Update scene graph hierarchy and game component configurations."
        elif "godot" in file_type or engine == "Godot":
            tags.extend(["godot", "scene-tree"])
            action = f"Update Godot scene {file_name}"[:49]
            nodes = facts.get("nodes_count", 0)
            root = facts.get("root_type", "Node")
            delta_points.append(f"Godot scene tree: {nodes} nodes (Root: {root})")
            if facts.get("node_types"):
                delta_points.append(f"Node classes: {', '.join(facts['node_types'][:3])}")
            intent = "Update game object nodes, spatial transforms, and script bindings."
        elif "unreal" in file_type or engine == "Unreal Engine":
            tags.extend(["unreal-engine", "uasset"])
            action = f"Update Unreal project {file_name}"[:49]
            v = facts.get("version", "")
            if v:
                delta_points.append(f"Unreal Engine version association: {v}")
            plugins = facts.get("plugins", [])
            if plugins:
                delta_points.append(f"Active modules/plugins: {', '.join(plugins[:3])}")
            intent = "Update engine plugins, gameplay modules, and asset targets."
        else:
            action = f"Update game asset {file_name}"[:49]
            delta_points.append("Updated game engine asset resources")
            intent = "Update interactive game assets and level components."

        if not delta_points:
            delta_points.append(f"Updated {engine} project data")

        return DifferOutput(action, delta_points, intent, tags)

    def _analyze_design_change(
        self,
        file_name: str,
        file_type: str,
        raw_diff: str,
        prev_meta: Any,
        curr_meta: Any,
        facts: Optional[Dict[str, Any]] = None,
    ) -> DifferOutput:
        delta_points: List[str] = []
        tags = ["ui-ux", "graphic-design"]
        facts = facts or {}
        tool = facts.get("design_tool", "Design")

        if "sketch" in file_type or tool == "Sketch":
            tags.extend(["sketch", "artboards"])
            action = f"Update Sketch artboards {file_name}"[:49]
            pages = facts.get("pages_count", 0)
            abs_list = facts.get("artboards", [])
            delta_points.append(f"Sketch document: {pages} pages, {len(abs_list)} artboards")
            if abs_list:
                delta_points.append(f"Artboards: {', '.join(abs_list[:3])}")
            intent = "Refine UI wireframes, design components, and design system tokens."
        elif "krita" in file_type or tool == "Krita":
            tags.extend(["krita", "digital-painting"])
            action = f"Update Krita artwork {file_name}"[:49]
            w, h = facts.get("width"), facts.get("height")
            layers = facts.get("layers_count", 0)
            if w and h:
                delta_points.append(f"Canvas resolution: {w}x{h}")
            if layers:
                delta_points.append(f"Painting layers: {layers} layers")
            intent = "Refine digital painting layers, brushes, and color values."
        elif "gimp" in file_type:
            tags.extend(["gimp", "raster"])
            action = f"Update GIMP composition {file_name}"[:49]
            delta_points.append("Updated GIMP multi-layer composition")
            intent = "Update image editing layers and raster masks."
        else:
            action = f"Update design asset {file_name}"[:49]
            delta_points.append("Updated design document assets")
            intent = "Update visual graphics and vector layouts."

        return DifferOutput(action, delta_points, intent, tags)

    def _analyze_scientific_change(
        self,
        file_name: str,
        file_type: str,
        raw_diff: str,
        prev_meta: Any,
        curr_meta: Any,
        facts: Optional[Dict[str, Any]] = None,
    ) -> DifferOutput:
        delta_points: List[str] = []
        tags = ["data-science", "analytics"]
        facts = facts or {}

        if "parquet" in file_type:
            tags.append("parquet")
            action = f"Update Parquet dataset {file_name}"[:49]
            delta_points.append("Updated Apache Parquet columnar table partitions")
            intent = "Update analytical dataset records and columnar schemas."
        else:
            tags.append("scientific-computing")
            action = f"Update scientific dataset {file_name}"[:49]
            delta_points.append("Updated multidimensional arrays and scientific datasets")
            intent = "Update experimental data arrays and observation matrices."

        return DifferOutput(action, delta_points, intent, tags)

    def _analyze_media_change(
        self,
        file_name: str,
        file_type: str,
        raw_diff: str,
        prev_meta: Any,
        curr_meta: Any,
        vision_summary: str,
    ) -> DifferOutput:
        delta_points: List[str] = []
        tags: List[str] = ["multimedia"]

        if file_type.startswith("video/"):
            tags.extend(["video-production", file_type.split("/")[-1]])
            res = f"{curr_meta.get('width')}x{curr_meta.get('height')}" if curr_meta.get("width") else None
            fps = curr_meta.get("fps")
            codec = curr_meta.get("video_codec") or "video"

            if res:
                delta_points.append(f"Video frame raster geometry: {res}")
            if fps:
                delta_points.append(f"Playback framerate: {fps} fps")
            if curr_meta.get("duration_seconds"):
                delta_points.append(f"Duration: {curr_meta.get('duration_seconds')}s")

            action = f"Update {file_name} ({res or codec})"
            if len(action) >= 50:
                action = f"Update video stream {file_name}"[:49]
            intent = "Update video render output and timeline master stream."

        elif file_type.startswith("audio/"):
            tags.extend(["audio-engineering", file_type.split("/")[-1]])
            sr = curr_meta.get("sample_rate_hz")
            ch = curr_meta.get("channels")
            layout = "Stereo" if ch == 2 else ("Mono" if ch == 1 else f"{ch}ch")

            if sr:
                delta_points.append(f"Audio sampling rate: {sr} Hz")
            if ch:
                delta_points.append(f"Channel layout: {layout}")
            if curr_meta.get("bit_depth"):
                delta_points.append(f"Quantization bit depth: {curr_meta.get('bit_depth')}-bit")

            action = f"Update audio master {file_name}"
            if len(action) >= 50:
                action = f"Update audio {file_name}"[:49]
            intent = "Update master audio track and acoustic mix balance."

        else:  # Image
            tags.extend(["image-asset", file_type.split("/")[-1]])
            w, h = curr_meta.get("width"), curr_meta.get("height")
            fmt = curr_meta.get("format", "Image")
            if w and h:
                delta_points.append(f"Canvas resolution: {w}x{h}")
            if curr_meta.get("mode"):
                delta_points.append(f"Color profile mode: {curr_meta.get('mode')}")

            action = f"Update {file_name} ({w}x{h})" if w and h else f"Update {file_name} image"
            if len(action) >= 50:
                action = f"Update image {file_name}"[:49]
            intent = "Update visual graphics asset and raster texture."

        if vision_summary and vision_summary not in delta_points:
            delta_points.append(vision_summary)

        return DifferOutput(action[:49], delta_points, intent, tags)

    def _analyze_creative_change(
        self,
        file_name: str,
        file_type: str,
        raw_diff: str,
        prev_meta: Any,
        curr_meta: Any,
        vision_summary: str,
    ) -> DifferOutput:
        delta_points: List[str] = []
        tags: List[str] = ["creative-suite"]

        if file_type == "creative/premiere":
            tags.extend(["adobe-premiere", "nle-edit"])
            seqs = curr_meta.get("sequences", [])
            tracks = curr_meta.get("tracks", {})
            if seqs:
                delta_points.append(f"Active timeline sequences: {', '.join(seqs[:3])}")
            if tracks:
                delta_points.append(f"Track layout: {tracks.get('video_tracks', 0)} V-tracks, {tracks.get('audio_tracks', 0)} A-tracks")
            action = f"Update Premiere edit timeline {file_name}"
            intent = "Refine video sequence cuts, transitions, and track routing."

        elif file_type == "creative/photoshop":
            tags.extend(["photoshop", "layer-comp"])
            w, h = curr_meta.get("width"), curr_meta.get("height")
            mode = curr_meta.get("color_mode", "RGB")
            if w and h:
                delta_points.append(f"Photoshop canvas resolution: {w}x{h}")
            if curr_meta.get("channels"):
                delta_points.append(f"Color channels: {curr_meta.get('channels')} ({mode})")
            action = f"Update Photoshop composition {file_name}"
            intent = "Adjust graphic layout layers, color grading, and raster masks."

        elif file_type == "creative/blender":
            tags.extend(["blender-3d", "scene-graph"])
            v = curr_meta.get("blender_version", "3D")
            delta_points.append(f"Blender project version: {v}")
            action = f"Update Blender 3D scene {file_name}"
            intent = "Update 3D mesh assets, materials, and scene composition."

        elif file_type == "creative/audacity":
            tags.extend(["audacity", "multitrack"])
            tracks = curr_meta.get("tracks", [])
            delta_points.append(f"Multitrack session: {len(tracks)} audio channels")
            action = f"Update Audacity audio session {file_name}"
            intent = "Adjust audio track envelopes, stems, and multi-channel mix."

        elif file_type.startswith("document/"):
            tags.extend(["documentation", "office"])
            if curr_meta.get("word_count"):
                delta_points.append(f"Document volume: {curr_meta.get('word_count')} words")
            if curr_meta.get("sheet_count"):
                delta_points.append(f"Workbook sheets: {curr_meta.get('sheet_count')}")
            if curr_meta.get("slide_count"):
                delta_points.append(f"Presentation slides: {curr_meta.get('slide_count')}")
            if curr_meta.get("estimated_pages"):
                delta_points.append(f"Document page count: {curr_meta.get('estimated_pages')} pages")
            action = f"Update document {file_name}"
            intent = "Revise documentation content, presentation, and data tables."

        else:
            tags.extend(["project-archive"])
            delta_points.append(f"Updated {file_name} project payload")
            action = f"Update creative asset {file_name}"
            intent = "Update application project state and workspace asset."

        if vision_summary and vision_summary not in delta_points:
            delta_points.append(vision_summary)

        if len(action) >= 50:
            action = f"Update {file_name}"[:49]

        return DifferOutput(action[:49], delta_points, intent, tags)
