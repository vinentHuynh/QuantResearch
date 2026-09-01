# Compile-check the two strategies against the installed NinjaTrader 8 assemblies
# WITHOUT launching NinjaTrader. Catches every API/signature error the NinjaScript
# editor would catch on F5; proves nothing about runtime behaviour.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\build_check.ps1

$ErrorActionPreference = "Stop"

$fw  = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319"
$nt  = "C:\Program Files\NinjaTrader 8\bin"
$src = $PSScriptRoot
$out = Join-Path $env:TEMP "ntcheck.dll"

# Prefer the USER's compiled NinjaTrader.Custom.dll -- that is what NinjaTrader
# actually links against on F5, and it is newer than the seed copy shipped in
# Program Files. GetFolderPath resolves a OneDrive-redirected Documents folder,
# which a hardcoded $env:USERPROFILE\Documents does not.
$userCustom = Join-Path ([Environment]::GetFolderPath('MyDocuments')) `
                        "NinjaTrader 8\bin\Custom\NinjaTrader.Custom.dll"
$seedCustom = "$nt\Custom\Backup\NinjaTrader.Custom.dll"
$custom = if (Test-Path $userCustom) { $userCustom } else { $seedCustom }

# NinjaTrader.Vendor.dll is deliberately NOT referenced: it mirrors the same
# NinjaTrader.NinjaScript.Strategies.Strategy type as NinjaTrader.Custom.dll and
# referencing both gives CS0433 (type exists in two assemblies).
$refs = @(
    "$fw\System.dll"
    "$fw\System.Core.dll"
    "$fw\System.Xml.dll"
    "$fw\System.Data.dll"
    "$fw\System.Drawing.dll"
    "$fw\System.ComponentModel.DataAnnotations.dll"
    "$fw\System.Xaml.dll"
    "$fw\WPF\WindowsBase.dll"
    "$fw\WPF\PresentationCore.dll"
    "$fw\WPF\PresentationFramework.dll"
    "$nt\NinjaTrader.Core.dll"
    "$nt\NinjaTrader.Gui.dll"
    $custom
)

$missing = $refs | Where-Object { -not (Test-Path $_) }
if ($missing) {
    Write-Host "Missing reference assemblies:" -ForegroundColor Red
    $missing | ForEach-Object { Write-Host "  $_" }
    exit 1
}

$files = Get-ChildItem $src -Filter *.cs | Select-Object -ExpandProperty FullName
if (-not $files) { Write-Host "No .cs files in $src" -ForegroundColor Red; exit 1 }

$args = @("/nologo", "/target:library", "/platform:x64", "/langversion:5", "/warn:4",
          "/out:`"$out`"")
$args += $refs  | ForEach-Object { "/r:`"$_`"" }
$args += $files | ForEach-Object { "`"$_`"" }

Write-Host "Compiling $($files.Count) file(s) against NinjaTrader $((Get-Item "$nt\NinjaTrader.exe").VersionInfo.FileVersion)..."
& "$fw\csc.exe" @args
if ($LASTEXITCODE -eq 0) {
    Write-Host "OK - no errors, no warnings. -> $out" -ForegroundColor Green
} else {
    Write-Host "FAILED (exit $LASTEXITCODE)" -ForegroundColor Red
}
exit $LASTEXITCODE
