"""Sentinel AI Design System - Pixel-accurate reference image implementation.

This module defines the visual design system inspired by the reference image,
providing consistent theming, colors, typography, and styling across all pages.
"""

from __future__ import annotations

from typing import Any, Final

# ============================================================
# COLOR PALETTE
# ============================================================

# Background colors
BG_PRIMARY: Final[str] = "#02050A"  # Near-black primary background
BG_SECONDARY: Final[str] = "#06101C"  # Deep navy secondary
BG_PANEL: Final[str] = "#071321"  # Panel background
BG_SIDEBAR: Final[str] = "#08142A"  # Sidebar background
BG_HEADER: Final[str] = "#040810"  # Header background

# Neon accent colors
ACCENT_NEON: Final[str] = "#00D9FF"  # Primary cyan neon
ACCENT_SECONDARY: Final[str] = "#00A8FF"  # Secondary cyan
ACCENT_BLUE: Final[str] = "#1677FF"  # Accent blue
ACCENT_PURPLE: Final[str] = "#9B6CFF"  # Purple accent

# Status colors
STATUS_POSITIVE: Final[str] = "#00E5A0"  # Green
STATUS_WARNING: Final[str] = "#FFB020"  # Warning
STATUS_DANGER: Final[str] = "#FF4D5E"  # Danger

# Text colors
TEXT_PRIMARY: Final[str] = "#F2F7FF"  # Primary text
TEXT_SECONDARY: Final[str] = "#8FA7C2"  # Secondary text
TEXT_MUTED: Final[str] = "#5D728B"  # Muted text

# Border colors
BORDER_DEFAULT: Final[str] = "rgba(0, 200, 255, 0.20)"  # Default border
BORDER_HOVER: Final[str] = "rgba(0, 220, 255, 0.60)"  # Hover border


# ============================================================
# TYPOGRAPHY SYSTEM
# ============================================================

# Font family - Inter, fallback to system UI
FONT_FAMILY: Final[str] = "Inter, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"

# Font sizes
TEXT_XS: Final[str] = "0.65rem"
TEXT_SM: Final[str] = "0.75rem"
TEXT_BASE: Final[str] = "0.875rem"
TEXT_LG: Final[str] = "1.125rem"
TEXT_XL: Final[str] = "1.5rem"
TEXT_2XL: Final[str] = "2rem"
TEXT_3XL: Final[str] = "3rem"

# Font weights
FONT_WEIGHT_LIGHT: Final[int] = 300
FONT_WEIGHT_NORMAL: Final[int] = 400
FONT_WEIGHT_MEDIUM: Final[int] = 500
FONT_WEIGHT_SEMIBOLD: Final[int] = 600
FONT_WEIGHT_BOLD: Final[int] = 700


# ============================================================
# SPACING SYSTEM
# ============================================================

SPACER_1: Final[str] = "0.25rem"   # 4px
SPACER_2: Final[str] = "0.5rem"    # 8px
SPACER_3: Final[str] = "0.75rem"   # 12px
SPACER_4: Final[str] = "1rem"      # 16px
SPACER_5: Final[str] = "1.5rem"    # 24px
SPACER_6: Final[str] = "2rem"      # 32px
SPACER_8: Final[str] = "3rem"      # 48px


# ============================================================
# BORDER RADIUS
# ============================================================

RADIUS_SM: Final[str] = "6px"
RADIUS_MD: Final[str] = "10px"
RADIUS_LG: Final[str] = "16px"
RADIUS_XL: Final[str] = "24px"


# ============================================================
# SHADOWS & GLOW
# ==========================================================--

SHADOW_SM: Final[str] = "0 1px 2px rgba(0, 0, 0, 0.3), 0 1px 3px rgba(0, 0, 0, 0.15)"
SHADOW_MD: Final[str] = "0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06)"
SHADOW_LG: Final[str] = "0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05)"

# Neon glow effects
GLOW_NEON: Final[str] = "0 0 15px rgba(0, 217, 255, 0.4), 0 0 30px rgba(0, 217, 255, 0.2)"
GLOW_BLUE: Final[str] = "0 0 20px rgba(22, 119, 255, 0.4)"
GLOW_CYAN: Final[str] = "0 0 15px rgba(0, 200, 255, 0.5)"
GLOW_PULSE: Final[str] = "0 0 20px rgba(0, 217, 255, 0.3), inset 0 0 20px rgba(0, 217, 255, 0.1)"


# ============================================================
# TRANSITIONS
# ============================================================

TRANSITION_FAST: Final[str] = "all 0.15s ease"
TRANSITION_MEDIUM: Final[str] = "all 0.25s ease"
TRANSITION_SLOW: Final[str] = "all 0.5s ease"


# ============================================================
# CHART CONFIGURATION
# ============================================================

CHART_BACKGROUND: Final[str] = "rgba(2, 5, 10, 0.8)"
CHART_GRID: Final[str] = "rgba(0, 200, 255, 0.1)"
CHART_AXIS: Final[str] = "rgba(0, 200, 255, 0.4)"
CHART_LINE: Final[str] = "#00D9FF"


# ============================================================
# STATUS INDICATORS
# ============================================================

STATUS_DOT_SIZE: Final[int] = 6
STATUS_DOT_GLOW: Final[str] = "0 0 8px currentColor"


# ============================================================
# EXPORT DESIGN TOKENS
# ============================================================

__all__ = [
    "BG_PRIMARY", "BG_SECONDARY", "BG_PANEL", "BG_SIDEBAR", "BG_HEADER",
    "ACCENT_NEON", "ACCENT_SECONDARY", "ACCENT_BLUE", "ACCENT_PURPLE",
    "STATUS_POSITIVE", "STATUS_WARNING", "STATUS_DANGER",
    "TEXT_PRIMARY", "TEXT_SECONDARY", "TEXT_MUTED",
    "BORDER_DEFAULT", "BORDER_HOVER",
    "FONT_FAMILY",
    "TEXT_XS", "TEXT_SM", "TEXT_BASE", "TEXT_LG", "TEXT_XL", "TEXT_2XL", "TEXT_3XL",
    "FONT_WEIGHT_LIGHT", "FONT_WEIGHT_NORMAL", "FONT_WEIGHT_MEDIUM", "FONT_WEIGHT_SEMIBOLD", "FONT_WEIGHT_BOLD",
    "SPACER_1", "SPACER_2", "SPACER_3", "SPACER_4", "SPACER_5", "SPACER_6", "SPACER_8",
    "RADIUS_SM", "RADIUS_MD", "RADIUS_LG", "RADIUS_XL",
    "SHADOW_SM", "SHADOW_MD", "SHADOW_LG",
    "GLOW_NEON", "GLOW_BLUE", "GLOW_CYAN", "GLOW_PULSE",
    "TRANSITION_FAST", "TRANSITION_MEDIUM", "TRANSITION_SLOW",
    "CHART_BACKGROUND", "CHART_GRID", "CHART_AXIS", "CHART_LINE",
    "STATUS_DOT_SIZE", "STATUS_DOT_GLOW",
]


# Design token values for CSS injection
DESIGN_CSS = f"""
:root {{
    --bg-primary: {BG_PRIMARY};
    --bg-secondary: {BG_SECONDARY};
    --bg-panel: {BG_PANEL};
    --bg-sidebar: {BG_SIDEBAR};
    --bg-header: {BG_HEADER};
    
    --accent-neon: {ACCENT_NEON};
    --accent-secondary: {ACCENT_SECONDARY};
    --accent-blue: {ACCENT_BLUE};
    --accent-purple: {ACCENT_PURPLE};
    
    --status-positive: {STATUS_POSITIVE};
    --status-warning: {STATUS_WARNING};
    --status-danger: {STATUS_DANGER};
    
    --text-primary: {TEXT_PRIMARY};
    --text-secondary: {TEXT_SECONDARY};
    --text-muted: {TEXT_MUTED};
    
    --border-default: {BORDER_DEFAULT};
    --border-hover: {BORDER_HOVER};
    
    --font-family: {FONT_FAMILY};
    
    --text-xs: {TEXT_XS};
    --text-sm: {TEXT_SM};
    --text-base: {TEXT_BASE};
    --text-lg: {TEXT_LG};
    --text-xl: {TEXT_XL};
    --text-2xl: {TEXT_2XL};
    --text-3xl: {TEXT_3XL};
    
    --font-weight-light: {FONT_WEIGHT_LIGHT};
    --font-weight-normal: {FONT_WEIGHT_NORMAL};
    --font-weight-medium: {FONT_WEIGHT_MEDIUM};
    --font-weight-semibold: {FONT_WEIGHT_SEMIBOLD};
    --font-weight-bold: {FONT_WEIGHT_BOLD};
    
    --space-1: {SPACER_1};
    --space-2: {SPACER_2};
    --space-3: {SPACER_3};
    --space-4: {SPACER_4};
    --space-5: {SPACER_5};
    --space-6: {SPACER_6};
    --space-8: {SPACER_8};
    
    --radius-sm: {RADIUS_SM};
    --radius-md: {RADIUS_MD};
    --radius-lg: {RADIUS_LG};
    --radius-xl: {RADIUS_XL};
    
    --shadow-sm: {SHADOW_SM};
    --shadow-md: {SHADOW_MD};
    --shadow-lg: {SHADOW_LG};
    
    --glow-neon: {GLOW_NEON};
    --glow-blue: {GLOW_BLUE};
    --glow-cyan: {GLOW_CYAN};
    --glow-pulse: {GLOW_PULSE};
    
    --transition-fast: {TRANSITION_FAST};
    --transition-medium: {TRANSITION_MEDIUM};
    --transition-slow: {TRANSITION_SLOW};
    
    --chart-background: {CHART_BACKGROUND};
    --chart-grid: {CHART_GRID};
    --chart-axis: {CHART_AXIS};
    --chart-line: {CHART_LINE};
    
    --status-dot-size: {STATUS_DOT_SIZE};
    --status-dot-glow: {STATUS_DOT_GLOW};
}}

*,
*::before,
*::after {{
    box-sizing: border-box;
    margin: 0;
    padding: 0;
}}

html {{
    font-family: var(--font-family);
    -webkit-text-size-adjust: 100%;
    touch-action: manipulation;
}}

body {{
    font-family: var(--font-family);
    background-color: var(--bg-primary);
    color: var(--text-primary);
    min-height: 100vh;
    line-height: 1.5;
}}

a {{
    color: inherit;
    text-decoration: none;
}}

img,
svg {{
    max-width: 100%;
    height: auto;
}}

button,
input,
select,
textarea {{
    font-family: inherit;
    font-size: 100%;
    line-height: inherit;
}}

/* Reduced motion */
@media (prefers-reduced-motion: reduce) {{
    * {{
        transition: none !important;
        animation: none !important;
    }}
}}
"""