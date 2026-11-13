"""Semantic analyzer for source code (Python, Rust, C, C++)."""

from __future__ import annotations
import ast
import re
from typing import Any, Dict, List, Optional, Set

from vcx.diff.analyzers.base import AnalysisResult, BaseAnalyzer


class SourceCodeAnalyzer(BaseAnalyzer):
    def analyze(
        self,
        old_content: Optional[bytes],
        new_content: Optional[bytes],
        file_name: str,
    ) -> AnalysisResult:
        old_text = old_content.decode("utf-8", errors="replace") if old_content else ""
        new_text = new_content.decode("utf-8", errors="replace") if new_content else ""

        raw_diff = self.compute_text_diff(old_text, new_text, file_name)

        if file_name.endswith((".py", ".pyi")):
            old_meta = self._analyze_python(old_text)
            new_meta = self._analyze_python(new_text)
        elif file_name.endswith(".rs"):
            old_meta = self._analyze_rust(old_text)
            new_meta = self._analyze_rust(new_text)
        else:  # C / C++ / Generic
            old_meta = self._analyze_c(old_text)
            new_meta = self._analyze_c(new_text)

        domain_facts = self._compute_code_delta_facts(old_meta, new_meta, raw_diff)

        return AnalysisResult(
            previous_metadata=old_meta,
            current_metadata=new_meta,
            raw_diff=raw_diff,
            vision_summary="",
            domain_facts=domain_facts,
        )

    def _analyze_python(self, code: str) -> Dict[str, Any]:
        if not code.strip():
            return {"functions": {}, "classes": {}, "imports": [], "loc": 0}

        meta: Dict[str, Any] = {
            "functions": {},
            "classes": {},
            "imports": [],
            "loc": len(code.splitlines()),
            "control_flow": {"loops": 0, "try_except": 0, "with_blocks": 0},
        }

        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    args = [a.arg for a in node.args.args]
                    meta["functions"][node.name] = {
                        "args": args,
                        "is_async": isinstance(node, ast.AsyncFunctionDef),
                        "decorators": [
                            ast.unparse(d) if hasattr(ast, "unparse") else str(d)
                            for d in node.decorator_list
                        ],
                    }
                elif isinstance(node, ast.ClassDef):
                    meta["classes"][node.name] = {
                        "bases": [
                            ast.unparse(b) if hasattr(ast, "unparse") else str(b)
                            for b in node.bases
                        ],
                    }
                elif isinstance(node, ast.Import):
                    for n in node.names:
                        meta["imports"].append(n.name)
                elif isinstance(node, ast.ImportFrom):
                    mod = node.module or ""
                    for n in node.names:
                        meta["imports"].append(f"{mod}.{n.name}")
                elif isinstance(node, (ast.For, ast.While)):
                    meta["control_flow"]["loops"] += 1
                elif isinstance(node, ast.Try):
                    meta["control_flow"]["try_except"] += 1
                elif isinstance(node, ast.With):
                    meta["control_flow"]["with_blocks"] += 1
        except SyntaxError:
            # Fallback regex if AST parsing fails
            meta["functions"] = {
                m.group(1): {"args": []}
                for m in re.finditer(r"def\s+([a-zA-Z0-9_]+)\s*\(", code)
            }
            meta["classes"] = {
                m.group(1): {}
                for m in re.finditer(r"class\s+([a-zA-Z0-9_]+)", code)
            }

        return meta

    def _analyze_rust(self, code: str) -> Dict[str, Any]:
        meta: Dict[str, Any] = {
            "functions": {},
            "structs": [],
            "traits": [],
            "memory_primitives": {
                "unsafe_blocks": len(re.findall(r"\bunsafe\b", code)),
                "allocations": len(re.findall(r"\b(Box|Arc|Rc|Vec|alloc)\b", code)),
                "mutex_locks": len(re.findall(r"\b(Mutex|RwLock)\b", code)),
            },
            "loc": len(code.splitlines()),
        }

        # Rust function signatures
        fn_pattern = re.compile(
            r"(?:pub\s+)?(?:async\s+)?fn\s+([a-zA-Z0-9_]+)\s*(?:<[^>]+>)?\s*\(([^)]*)\)(?:\s*->\s*([^{]+))?"
        )
        for m in fn_pattern.finditer(code):
            name, params, ret = m.group(1), m.group(2).strip(), (m.group(3) or "").strip()
            meta["functions"][name] = {
                "params": [p.strip() for p in params.split(",") if p.strip()],
                "return_type": ret,
            }

        meta["structs"] = re.findall(r"(?:pub\s+)?struct\s+([a-zA-Z0-9_]+)", code)
        meta["traits"] = re.findall(r"(?:pub\s+)?trait\s+([a-zA-Z0-9_]+)", code)
        return meta

    def _analyze_c(self, code: str) -> Dict[str, Any]:
        meta: Dict[str, Any] = {
            "functions": {},
            "memory_management": {
                "malloc_calls": len(re.findall(r"\b(malloc|calloc|realloc)\b", code)),
                "free_calls": len(re.findall(r"\bfree\b", code)),
                "pointer_refs": len(re.findall(r"->|\*", code)),
            },
            "loc": len(code.splitlines()),
        }

        # C/C++ function definitions
        c_fn = re.compile(
            r"([a-zA-Z0-9_*]+\s+)+([a-zA-Z0-9_]+)\s*\(([^)]*)\)\s*\{"
        )
        for m in c_fn.finditer(code):
            fn_name = m.group(2)
            if fn_name not in ("if", "while", "for", "switch"):
                meta["functions"][fn_name] = {
                    "args": [a.strip() for a in m.group(3).split(",") if a.strip()]
                }
        return meta

    def _compute_code_delta_facts(
        self, old_meta: Dict[str, Any], new_meta: Dict[str, Any], raw_diff: str
    ) -> Dict[str, Any]:
        old_fns = set(old_meta.get("functions", {}).keys())
        new_fns = set(new_meta.get("functions", {}).keys())

        added_fns = sorted(list(new_fns - old_fns))
        removed_fns = sorted(list(old_fns - new_fns))
        retained_fns = old_fns & new_fns

        modified_signatures = []
        for fn in retained_fns:
            if old_meta["functions"][fn] != new_meta["functions"][fn]:
                modified_signatures.append(fn)

        mem_facts = []
        if "memory_primitives" in new_meta and "memory_primitives" in old_meta:
            new_unsafe = new_meta["memory_primitives"]["unsafe_blocks"]
            old_unsafe = old_meta["memory_primitives"]["unsafe_blocks"]
            if new_unsafe != old_unsafe:
                mem_facts.append(f"Unsafe blocks changed from {old_unsafe} to {new_unsafe}")

        if "memory_management" in new_meta and "memory_management" in old_meta:
            new_frees = new_meta["memory_management"]["free_calls"]
            old_frees = old_meta["memory_management"]["free_calls"]
            if new_frees != old_frees:
                mem_facts.append(f"Free() calls changed from {old_frees} to {new_frees}")

        return {
            "added_functions": added_fns,
            "removed_functions": removed_fns,
            "modified_signatures": modified_signatures,
            "memory_facts": mem_facts,
            "loc_delta": new_meta.get("loc", 0) - old_meta.get("loc", 0),
        }
