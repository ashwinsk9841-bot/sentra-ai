"""Streamlit presentation layer.

Modules:
    theme       colour tokens, Altair base config, formatting helpers
    charts      Altair figures built from service frames
    components  reusable widgets (KPI rows, risk header, empty states)
    state       cached services, cached reads, shared selectors
"""

from __future__ import annotations

__all__ = ["charts", "components", "state", "theme"]
