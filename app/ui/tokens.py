"""Design tokens for TikTok YouTube Studio.

All measurements follow a 4px/8px grid system.
Dark theme optimized for desktop clarity, contrast, and elegance.
"""

from __future__ import annotations

# ==============================================================================
# Color Palette
# ==============================================================================

# Backgrounds
BG_APP = "#0c0e15"          # Main window background
BG_SIDEBAR = "#121520"      # Sidebar background
BG_CARD = "#171a27"         # Card / container background
BG_CARD_HOVER = "#1c2132"   # Card hover
BG_CARD_ACTIVE = "#21273b"  # Card selected/active
BG_INPUT = "#1a1e2d"        # Input fields
BG_INPUT_HOVER = "#202538"  # Input hover
BG_INPUT_FOCUS = "#242a3f"  # Input focus
BG_HEADER = "#151824"       # Tables / sub-headers
BG_MODAL = "#151826"        # Dialogs / Popups

# Borders
BORDER_SUBTLE = "#202536"   # Very subtle dividers
BORDER_DEFAULT = "#2a3147"  # Standard borders
BORDER_HOVER = "#3c4664"    # Hovered borders
BORDER_FOCUS = "#3b82f6"    # Focused control border

# Text & Icon Colors
TEXT_PRIMARY = "#f8fafc"    # High-emphasis text
TEXT_SECONDARY = "#94a3b8"  # Medium-emphasis labels, secondary info
TEXT_MUTED = "#64748b"      # Disabled, placeholders, tertiary
TEXT_INVERTED = "#ffffff"   # On dark/colored backgrounds

# Accent / Brand Colors
PRIMARY = "#3b82f6"         # Blue brand accent
PRIMARY_HOVER = "#2563eb"
PRIMARY_ACTIVE = "#1d4ed8"
PRIMARY_BG = "#172554"
PRIMARY_MUTED = "rgba(59, 130, 246, 0.15)"

# Semantic aliases
COLOR_PRIMARY = PRIMARY
COLOR_PRIMARY_HOVER = PRIMARY_HOVER
COLOR_SUCCESS = "#10b981"
COLOR_WARNING = "#f59e0b"
COLOR_DANGER = "#ef4444"
COLOR_INFO = PRIMARY

SUCCESS = "#10b981"         # Green
SUCCESS_HOVER = "#059669"
SUCCESS_BG = "#064e3b"
SUCCESS_BORDER = "#047857"
SUCCESS_MUTED = "rgba(16, 185, 129, 0.15)"

WARNING = "#f59e0b"         # Amber
WARNING_HOVER = "#d97706"
WARNING_BG = "#78350f"
WARNING_BORDER = "#b45309"
WARNING_MUTED = "rgba(245, 158, 11, 0.15)"

DANGER = "#ef4444"          # Red
DANGER_HOVER = "#dc2626"
DANGER_BG = "#7f1d1d"
DANGER_BORDER = "#b91c1c"
DANGER_MUTED = "rgba(239, 68, 68, 0.15)"

INFO = "#0ea5e9"            # Cyan / Sky
INFO_HOVER = "#0284c7"
INFO_BG = "#0c4a6e"
INFO_BORDER = "#0369a1"
INFO_MUTED = "rgba(14, 165, 233, 0.15)"

# ==============================================================================
# Geometry & Spacing (4px / 8px Grid)
# ==============================================================================

SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 16
SPACE_LG = 24
SPACE_XL = 32
SPACE_2XL = 40

RADIUS_XS = 4
RADIUS_SM = 6
RADIUS_MD = 8
RADIUS_LG = 12
RADIUS_XL = 16
RADIUS_FULL = 9999

# Element Heights
HEIGHT_INPUT_SM = 32
HEIGHT_INPUT_MD = 38
HEIGHT_INPUT_LG = 44
HEIGHT_BTN_SM = 32
HEIGHT_BTN_MD = 38
HEIGHT_BTN_LG = 44

# Sidebar Dimensions
SIDEBAR_WIDTH_EXPANDED = 240
SIDEBAR_WIDTH_COLLAPSED = 68
SIDEBAR_COLLAPSE_THRESHOLD = 1100

# Window Constraints
WINDOW_MIN_WIDTH = 1000
WINDOW_MIN_HEIGHT = 640
WINDOW_DEFAULT_WIDTH = 1280
WINDOW_DEFAULT_HEIGHT = 760

# ==============================================================================
# Typography
# ==============================================================================

FONT_FAMILY = "Segoe UI"
FONT_FALLBACKS = '"Segoe UI", -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif'

# Point sizes (strictly > 0 to prevent QFont::setPointSize warning)
FONT_SIZE_XS = 10
FONT_SIZE_SM = 11
FONT_SIZE_MD = 12
FONT_SIZE_BASE = 13
FONT_SIZE_LG = 14
FONT_SIZE_XL = 16
FONT_SIZE_2XL = 18
FONT_SIZE_3XL = 22

FONT_WEIGHT_NORMAL = 400
FONT_WEIGHT_MEDIUM = 500
FONT_WEIGHT_SEMIBOLD = 600
FONT_WEIGHT_BOLD = 700
