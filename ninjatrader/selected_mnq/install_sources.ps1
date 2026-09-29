# Installs source only. Does not launch NinjaTrader, choose an account or enable.
$ErrorActionPreference = 'Stop'
$sourceDirectory = Join-Path $PSScriptRoot 'Strategies'
$destination = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'NinjaTrader 8\bin\Custom\Strategies'
if (-not (Test-Path -LiteralPath $destination -PathType Container)) {
    throw "NinjaTrader user Strategies directory is missing: $destination"
}
$names = @('WorkbenchMnqMinuteReversal.cs', 'WorkbenchMnqReversalCore.cs',
    'WorkbenchMnqOvernightBlock.cs', 'WorkbenchMnqOvernightRules.cs',
    'WorkbenchMnqTsmomOrb.cs', 'WorkbenchMnqTsmomOrbCore.cs')
$manifest = Get-Content -Raw -LiteralPath (Join-Path $PSScriptRoot 'validation.json') | ConvertFrom-Json
foreach ($name in $names) {
    $source = Join-Path $sourceDirectory $name
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "Bundle incomplete: $name" }
    $expected = ($manifest.files | Where-Object { $_.file -eq "Strategies/$name" }).sha256
    if (-not $expected -or (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash -ne $expected) {
        throw "Bundle source checksum mismatch: $name"
    }
}
$backupDirectory = Join-Path $PSScriptRoot ('install-backup-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
$installed = @()
foreach ($name in $names) {
    $source = Join-Path $sourceDirectory $name
    $target = Join-Path $destination $name
    $sourceHash = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash
    if (Test-Path -LiteralPath $target) {
        if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ne $sourceHash) {
            New-Item -ItemType Directory -Path $backupDirectory -Force | Out-Null
            Copy-Item -LiteralPath $target -Destination (Join-Path $backupDirectory $name)
        }
    }
    Copy-Item -LiteralPath $source -Destination $target -Force
    if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ne $sourceHash) { throw "Copy failed: $name" }
    $installed += [PSCustomObject]@{file=$name; destination=$target; sha256=$sourceHash.ToLowerInvariant()}
}
[PSCustomObject]@{
    installed_at = (Get-Date).ToUniversalTime().ToString('o')
    actions = 'Verified source copies only. No platform launch, native F5 compile, account selection or enabling.'
    files = $installed
} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'installation.json') -Encoding UTF8
Write-Output "Verified $($names.Count) source files in $destination"
Write-Output 'Selected strategies: Overnight Block, Minute Reversal, repaired TSMOM ORB.'
Write-Output 'Next: NinjaTrader > New > NinjaScript Editor > F5.'
