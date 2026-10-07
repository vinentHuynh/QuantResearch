# Market dataset archives

Snapshot created on October 7, 2026: **77 files in 17 ZIP archives**, totaling
**1,061.67 MiB compressed**. Each ZIP is independently extractable and smaller
than 95 MiB. Paths inside the ZIPs are relative to the repository root.

The snapshot includes:

- Root market Parquet files, the MNQ candle CSV, and the CME universe CSV.
- Databento minute-data caches and the four original vendor archives.
- MNQ one-minute and resampled candle files.
- September 29 ES and NQ updates, composite archives, and download metadata.
- Eight normalized workbench datasets, their metadata, and the dataset catalog.

Backtest results, trade exports, workbench databases, research state, and
temporary test data are excluded. Original files under `data/` remain intact.
This snapshot is a dataset transfer, not a complete workbench-state backup.

[manifest.json](manifest.json) records each archive and source file's size and
SHA-256 checksum. Every archived file was read back and verified against its
source checksum after compression.

## Restore

From the repository root in a fresh checkout, run this PowerShell block. It
verifies all ZIP checksums before extracting them into their original `data/`
paths. `-Force` replaces files at those paths, so use a fresh checkout to avoid
overwriting different local datasets.

```powershell
$manifest = Get-Content -Raw dataset-archives/manifest.json | ConvertFrom-Json
foreach ($archive in $manifest.archives) {
    $archivePath = Join-Path dataset-archives $archive.path
    $actualHash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash
    if ($actualHash -ne $archive.sha256) {
        throw "Checksum mismatch: $archivePath"
    }
}
foreach ($archive in $manifest.archives) {
    $archivePath = Join-Path dataset-archives $archive.path
    Expand-Archive -LiteralPath $archivePath -DestinationPath . -Force
}
```

Existing dataset metadata is preserved byte-for-byte, including original
absolute paths. Restoring the files alone does not recreate workbench database
registrations. On another machine, import the restored vendor archives through
the workbench's dataset import flow as needed.
