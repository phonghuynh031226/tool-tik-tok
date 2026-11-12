# Dot-source before installing, running, or testing: . .\scripts\project-env.ps1
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$env:TEMP = Join-Path $ProjectRoot '.tmp'
$env:TMP = $env:TEMP
$env:PIP_CACHE_DIR = Join-Path $ProjectRoot '.cache/pip'
$env:PYTHONPYCACHEPREFIX = Join-Path $ProjectRoot '.cache/pycache'
$env:UV_CACHE_DIR = Join-Path $ProjectRoot '.cache/uv'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $ProjectRoot '.cache/python'
$env:UV_PYTHON_BIN_DIR = Join-Path $ProjectRoot '.cache/python-bin'
$env:UV_TOOL_DIR = Join-Path $ProjectRoot '.cache/uv-tools'
$env:UV_TOOL_BIN_DIR = Join-Path $ProjectRoot '.cache/uv-bin'
$env:UV_NO_PROGRESS = '1'
$env:PIP_DISABLE_PIP_VERSION_CHECK = '1'
$env:PYTHONNOUSERSITE = '1'
New-Item -ItemType Directory -Force $env:TEMP,$env:PIP_CACHE_DIR,$env:PYTHONPYCACHEPREFIX | Out-Null
