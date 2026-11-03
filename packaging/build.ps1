<#
.SYNOPSIS
    Build the PDF Reader installer: dist\PDF-Reader-Setup-<version>.exe

.DESCRIPTION
    1. Runs the tests and the linter (skip with -SkipTests).
    2. Builds the app with PyInstaller into build\dist.
    3. Writes build\defines.iss from the app's constants.
    4. Compiles packaging\installer.iss with Inno Setup.
    5. Writes dist\SHA256SUMS.txt so downloads can be verified.

    Needs uv and Inno Setup 6.4+ (winget install --id JRSoftware.InnoSetup -e).

.PARAMETER SkipTests
    Don't run the tests and the linter first.

.PARAMETER SignTool
    Optional Inno Setup sign command for code signing, for example
    'signtool sign /a /fd sha256 /tr http://timestamp.digicert.com /td sha256 $f'.
#>
param(
    [switch]$SkipTests,
    [string]$SignTool = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Invoke-Step([string]$Name, [scriptblock]$Command) {
    Write-Host "==> $Name" -ForegroundColor Cyan
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "$Name failed (exit code $LASTEXITCODE)" }
}

if (-not $SkipTests) {
    Invoke-Step "Tests" { uv run pytest -q }
    Invoke-Step "Lint" { uv run ruff check . }
}

Invoke-Step "Build the app" {
    uv run pyinstaller packaging/pdf-reader.spec --noconfirm --clean `
        --distpath build/dist --workpath build/work
}
Invoke-Step "Installer settings" { uv run python packaging/write_defines.py build/defines.iss }

$iscc = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) {
    throw "Inno Setup 6 was not found. Install it with: winget install --id JRSoftware.InnoSetup -e"
}

$isccArgs = @("/Q", "packaging/installer.iss")
if ($SignTool) { $isccArgs = @("/DSignTool=$SignTool") + $isccArgs }
Invoke-Step "Build the installer" { & $iscc @isccArgs }

$setup = Get-ChildItem dist -Filter "PDF-Reader-Setup-*.exe" |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
$hash = (Get-FileHash $setup.FullName -Algorithm SHA256).Hash.ToLower()
"$hash  $($setup.Name)" | Set-Content -Encoding ascii dist/SHA256SUMS.txt
$sizeMb = [math]::Round($setup.Length / 1MB, 1)
Write-Host ""
Write-Host "Installer: $($setup.FullName) ($sizeMb MB)" -ForegroundColor Green
Write-Host "SHA-256:   $hash"
