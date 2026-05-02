param(
    [string]$PythonExe = "py",
    [switch]$Clean
)

Set-Location $PSScriptRoot

if ($Clean) {
    Remove-Item -Recurse -Force build, dist, Scent.spec -ErrorAction SilentlyContinue
}

& $PythonExe -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --onedir `
    --name Scent `
    --add-data "templates;templates" `
    --add-data "static;static" `
    --collect-all webview `
    desktop_main.py