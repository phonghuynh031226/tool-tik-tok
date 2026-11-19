$ErrorActionPreference = 'Stop'
. "$PSScriptRoot/project-env.ps1"
Set-Location -LiteralPath $ProjectRoot
$studioPython = Join-Path $ProjectRoot '.venv/Scripts/pythonw.exe'
if (-not (Test-Path -LiteralPath $studioPython)) {
    $studioPython = Join-Path (Split-Path -Parent $ProjectRoot) 'tool-tik-tok/.venv/Scripts/pythonw.exe'
}
if (-not (Test-Path -LiteralPath $studioPython)) {
    throw 'Python environment missing. Install requirements-dev.txt in the project .venv.'
}
# Exclude unrelated native tools (Poppler/OpenSSL/Qt) from DLL lookup.
$env:PATH = "$(Split-Path -Parent $studioPython);$env:SystemRoot/System32;$env:SystemRoot"
Remove-Item Env:PYTHONHOME,Env:PYTHONPATH -ErrorAction SilentlyContinue
$studioMain = Join-Path $ProjectRoot 'main.py'
$studioProcess = Start-Process -FilePath $studioPython -ArgumentList @('"' + $studioMain + '"') -WorkingDirectory $ProjectRoot -WindowStyle Normal -PassThru
$studioProcess.Id
