"""Process-local Windows native dependency isolation, before importing Qt/SDKs."""

import os
from pathlib import Path
import sys


def configure_native_environment() -> None:
    """Keep unrelated toolchain DLL directories out of delayed native loads.

    Does not change the machine/user PATH or disable TLS certificate validation.
    External project tools such as FFmpeg are resolved by explicit project paths.
    """
    if sys.platform != 'win32':
        return
    windows = Path(os.environ.get('SystemRoot', r'C:\Windows'))
    os.environ['PATH'] = os.pathsep.join(map(str, (
        Path(sys.executable).parent, windows / 'System32', windows,
    )))
