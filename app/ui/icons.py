"""Icon helper module for TikTok YouTube Studio using QtAwesome.

Replaces all unicode emojis with clean, professional vector icons.
Supports stateful colors (normal, hover, active, disabled).
"""

from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtGui import QIcon

from app.ui import tokens

logger = logging.getLogger(__name__)

# Semantic name mapping to bundled QtAwesome icon strings (Material Design Icons v6)
ICON_MAP = {
    # Navigation
    "nav_dashboard": "mdi6.view-dashboard",
    "nav_tools": "mdi6.tools",
    "nav_tiktok": "mdi6.video",
    "nav_ai": "mdi6.creation",
    "nav_youtube": "mdi6.youtube",
    "nav_history": "mdi6.history",
    "nav_settings": "mdi6.cog",
    # Actions
    "download": "mdi6.download",
    "paste": "mdi6.content-paste",
    "content-paste": "mdi6.content-paste",
    "folder": "mdi6.folder-open",
    "folder-open": "mdi6.folder-open",
    "browse": "mdi6.folder-open",
    "copy": "mdi6.content-copy",
    "content-copy": "mdi6.content-copy",
    "content-save": "mdi6.content-save",
    "restore": "mdi6.restore",
    "upload": "mdi6.upload",
    "play": "mdi6.play",
    "pause": "mdi6.pause",
    "refresh": "mdi6.refresh",
    "sync": "mdi6.sync",
    "chevron-left": "mdi6.chevron-left",
    "chevron-right": "mdi6.chevron-right",
    "chevron_left": "mdi6.chevron-left",
    "chevron_right": "mdi6.chevron-right",
    "export": "mdi6.file-delimited",
    "link": "mdi6.open-in-new",
    "open-in-new": "mdi6.open-in-new",
    "delete": "mdi6.trash-can",
    "trash-can": "mdi6.trash-can",
    "cancel": "mdi6.close-circle-outline",
    "close-circle": "mdi6.close-circle-outline",
    "close": "mdi6.close",
    "check": "mdi6.check-circle",
    "check-circle": "mdi6.check-circle",
    "key": "mdi6.key-variant",
    "eye": "mdi6.eye",
    "eye_off": "mdi6.eye-off",
    "test": "mdi6.flask",
    "flask": "mdi6.flask",
    # Accounts
    "user-add": "mdi6.account-plus",
    "account-plus": "mdi6.account-plus",
    "user-check": "mdi6.account-check",
    "account-check": "mdi6.account-check",
    "user-remove": "mdi6.account-remove",
    "account-remove": "mdi6.account-remove",
    # Status / Types
    "success": "mdi6.check-circle",
    "info": "mdi6.information",
    "warning": "mdi6.alert",
    "error": "mdi6.alert-circle",
    "shield": "mdi6.shield-check",
    "clock": "mdi6.clock-outline",
    "history": "mdi6.history",
    "video": "mdi6.video-vintage",
    "youtube": "mdi6.youtube",
    "author": "mdi6.account-circle-outline",
    "hash": "mdi6.pound",
    "tag": "mdi6.tag-multiple-outline",
    "sparkle": "mdi6.creation",
    "creation": "mdi6.creation",
    "logo": "mdi6.play-box-multiple",
}


def get_icon(
    name: str,
    color: Optional[str] = None,
    color_hover: Optional[str] = None,
    color_active: Optional[str] = None,
    color_disabled: Optional[str] = None,
    scale_factor: float = 1.0,
) -> QIcon:
    """Retrieve a state-aware QIcon by semantic key or direct qtawesome icon name.

    If name matches a key in ICON_MAP, the mapped name is used.
    Otherwise name is passed directly to qtawesome (e.g. 'mdi6.xxx').
    If the name lacks a prefix, 'mdi6.' is tried before falling back.
    Logs a warning if the icon cannot be resolved.
    """
    import qtawesome as qta

    icon_name = ICON_MAP.get(name)
    if not icon_name:
        if "." in name:
            icon_name = name
        else:
            # Try auto-prefixing with mdi6.
            icon_name = f"mdi6.{name}"

    c_normal = color or tokens.TEXT_SECONDARY
    c_hover = color_hover or tokens.PRIMARY
    c_active = color_active or tokens.PRIMARY_ACTIVE
    c_disabled = color_disabled or tokens.TEXT_MUTED

    try:
        icon = qta.icon(
            icon_name,
            color=c_normal,
            color_hover=c_hover,
            color_active=c_active,
            color_disabled=c_disabled,
            scale_factor=scale_factor,
        )
        if not icon.isNull():
            return icon
    except Exception as exc:
        logger.warning(
            "Icon lookup failed for '%s' (resolved as '%s'): %s",
            name,
            icon_name,
            exc,
        )

    # Secondary attempt if auto-prefixed wasn't tried or failed
    if icon_name != name and "." in name:
        try:
            icon = qta.icon(
                name,
                color=c_normal,
                color_hover=c_hover,
                color_active=c_active,
                color_disabled=c_disabled,
                scale_factor=scale_factor,
            )
            if not icon.isNull():
                return icon
        except Exception:
            pass

    logger.warning("Icon '%s' not found in QtAwesome library. Falling back to placeholder.", name)
    try:
        return qta.icon("mdi6.circle", color=c_normal)
    except Exception:
        return QIcon()


def get_colored_icon(name: str, color: str, scale_factor: float = 1.0) -> QIcon:
    """Get a fixed single-color icon (e.g. for status badges or alert toasts)."""
    return get_icon(
        name,
        color=color,
        color_hover=color,
        color_active=color,
        color_disabled=tokens.TEXT_MUTED,
        scale_factor=scale_factor,
    )


def get_state_icon(
    name: str,
    color: Optional[str] = None,
    color_hover: Optional[str] = None,
    color_active: Optional[str] = None,
    color_disabled: Optional[str] = None,
    scale_factor: float = 1.0,
) -> QIcon:
    """Retrieve a state-aware QIcon with distinct normal, hover, active and disabled colors."""
    return get_icon(name, color, color_hover, color_active, color_disabled, scale_factor)
