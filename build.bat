@echo off
setlocal EnableExtensions DisableDelayedExpansion
pushd "%~dp0"
if errorlevel 1 exit /b 1
set "PROJECT_ROOT=%CD%"
set "PYTHON=%PROJECT_ROOT%\.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo ERROR: Create a Python 3.12 .venv and install requirements-dev.txt first.
    popd
    exit /b 2
)
set "TEMP=%PROJECT_ROOT%\.tmp"
set "TMP=%TEMP%"
set "TMPDIR=%TEMP%"
set "PIP_CACHE_DIR=%PROJECT_ROOT%\.cache\pip"
set "PYTHONPYCACHEPREFIX=%PROJECT_ROOT%\.cache\pycache"
set "PYINSTALLER_CONFIG_DIR=%PROJECT_ROOT%\.cache\pyinstaller"
set "XDG_CACHE_HOME=%PROJECT_ROOT%\.cache"
set "MPLCONFIGDIR=%PROJECT_ROOT%\.cache\matplotlib"
set "PYTHONNOUSERSITE=1"
set "PYTHONHOME="
set "PYTHONPATH="
"%PYTHON%" -B -c "import sys; from app.core.paths import safe_path; assert sys.version_info[:2] == (3,12), 'Python 3.12 required'; [safe_path(p) for p in ('.tmp','.cache','build','dist','bin','bin/ffmpeg.exe','bin/ffprobe.exe')]"
if errorlevel 1 goto :failed
if not exist "%TEMP%" mkdir "%TEMP%"
if not exist "%PYINSTALLER_CONFIG_DIR%" mkdir "%PYINSTALLER_CONFIG_DIR%"
"%PYTHON%" -c "import PyInstaller"
if errorlevel 1 (
    echo ERROR: PyInstaller is missing. Install requirements-dev.txt into .venv.
    goto :failed
)
rem The spec uses EXE(exclude_binaries=True) + COLLECT: --onedir, console=False.
rem --onedir/--windowed are encoded in the spec, not valid overrides for a spec build.
"%PYTHON%" -m PyInstaller --noconfirm --clean --distpath "%PROJECT_ROOT%\dist" --workpath "%PROJECT_ROOT%\build" "%PROJECT_ROOT%\TikTokYouTubeStudio.spec"
if errorlevel 1 goto :failed
if not exist "%PROJECT_ROOT%\dist\TikTokYouTubeStudio\bin" mkdir "%PROJECT_ROOT%\dist\TikTokYouTubeStudio\bin"
if errorlevel 1 goto :failed
for %%F in (ffmpeg ffprobe) do (
    if exist "%PROJECT_ROOT%\bin\%%F.exe" (
        copy /Y "%PROJECT_ROOT%\bin\%%F.exe" "%PROJECT_ROOT%\dist\TikTokYouTubeStudio\bin\%%F.exe" >nul
        if errorlevel 1 goto :failed
    ) else (
        echo WARNING: bin\%%F.exe not found; not bundled.
    )
)
echo Build output: "%PROJECT_ROOT%\dist\TikTokYouTubeStudio\TikTokYouTubeStudio.exe"
popd
exit /b 0
:failed
echo BUILD FAILED. Read the preceding error. No successful build is claimed.
popd
exit /b 1
