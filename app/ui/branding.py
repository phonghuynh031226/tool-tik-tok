"""Single Source of Truth for Clivo application branding and identity assets.

Provides application metadata, versioning, and secure path resolution
for bundled brand assets (PNGs, SVGs, multi-resolution QIcons), compatible
with both standard development mode and PyInstaller frozen binaries.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap

from app.core.paths import resource_root, safe_path

APP_NAME: str = "Clivo"
APP_VERSION: str = "2.0.0"
APP_ID: str = "Clivo.App"
APP_TAGLINE: str = "TikTok → YouTube"
APP_DESCRIPTION: str = (
    "Quản lý toàn diện quy trình tải video TikTok, tạo nội dung tự động bằng AI "
    "và xuất bản lên các kênh YouTube."
)

# Supported icon sizes in assets/brand/
AVAILABLE_ICON_SIZES = (16, 32, 48, 64, 128, 256, 1024)


def get_brand_asset_path(filename: str) -> Path:
    """Return the absolute path to a brand asset file under assets/brand/."""
    return safe_path("assets", "brand", filename, root=resource_root())


def get_logo_icon_path(size: int = 64) -> Path:
    """Return the path to a specific resolution of the Clivo logo icon.

    If requested size is not exact, chooses the closest available size.
    """
    if size in AVAILABLE_ICON_SIZES:
        target_size = size
    else:
        target_size = min(AVAILABLE_ICON_SIZES, key=lambda s: abs(s - size))
    return get_brand_asset_path(f"clivo-icon-{target_size}.png")


def get_logo_svg_path() -> Path:
    """Return the path to clivo-logo.svg."""
    return get_brand_asset_path("clivo-logo.svg")


def get_icon_svg_path() -> Path:
    """Return the path to clivo-icon.svg."""
    return get_brand_asset_path("clivo-icon.svg")


def get_logo_full_path() -> Path:
    """Return the path to full lockup clivo-logo.png."""
    return get_brand_asset_path("clivo-logo.png")


def get_app_icon() -> QIcon:
    """Create and return a multi-resolution QIcon constructed from Clivo PNGs.

    Includes 16x16, 32x32, 48x48, 64x64, 128x128, 256x256 resolutions.
    """
    icon = QIcon()
    for size in (16, 32, 48, 64, 128, 256):
        path = get_logo_icon_path(size)
        if path.exists():
            icon.addFile(str(path), QSize(size, size))
    return icon


def get_logo_pixmap(size: int = 32) -> QPixmap:
    """Return a crisp QPixmap scaled smoothly to the requested size.

    Loads from high-res source (128px) and scales with SmoothTransformation
    to render beautifully on Windows at 100%, 125%, 150% and higher DPI scales.
    """
    source_size = 128 if size <= 64 else 256
    source_path = get_logo_icon_path(source_size)
    if not source_path.exists():
        source_path = get_logo_icon_path(64)

    pixmap = QPixmap(str(source_path))
    if not pixmap.isNull():
        return pixmap.scaled(
            size, size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    return QPixmap()


def get_window_title(subtitle: Optional[str] = None) -> str:
    """Format window title using APP_NAME as the source of truth."""
    if subtitle:
        return f"{APP_NAME} - {subtitle}"
    return APP_NAME


def get_dialog_title(title: str) -> str:
    """Format dialog title prefixed by APP_NAME if not already included."""
    if APP_NAME in title:
        return title
    return f"{APP_NAME} - {title}"
