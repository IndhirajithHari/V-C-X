"""Pluggable Domain Adapters for VCX Semantic Extraction.

Provides native metadata and AST extraction for specialized file types:
- FreeCAD parametric CAD models (.FCStd)
- Verilog and SystemVerilog hardware designs (.v, .sv)
"""

from __future__ import annotations
from vcx.adapters.freecad_adapter import FreeCADAdapter
from vcx.adapters.eda_adapter import EDAAdapter

__all__ = ["FreeCADAdapter", "EDAAdapter"]
