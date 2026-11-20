# Build FVS-Bridge.exe into bridge\dist (the app serves it to other computers from there when run from source;
# packaging\build.ps1 calls this and puts it in the installer).
#   powershell -ExecutionPolicy Bypass -File bridge\build.ps1
# Needs Go 1.24 or newer (go.dev/dl). The exe's icon is embedded with rsrc (fetched by `go run` the first time).
$ErrorActionPreference = "Stop"
$Here = $PSScriptRoot
$Root = Split-Path $Here
$go = (Get-Command go -ErrorAction SilentlyContinue).Source
if (-not $go) { $go = Join-Path $env:LOCALAPPDATA "Programs\go\bin\go.exe" }
if (-not (Test-Path $go)) { throw "Go not found: install it from https://go.dev/dl/" }

$Version = (Select-String -Path "$Root\studio\__init__.py" -Pattern '__version__\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
Push-Location $Here
try {
    & $go run github.com/akavel/rsrc@v0.10.2 -ico icon.ico -o rsrc_windows_amd64.syso
    if ($LASTEXITCODE -ne 0) { throw "rsrc failed" }
    New-Item -ItemType Directory -Force dist | Out-Null
    $env:CGO_ENABLED = "0"
    & $go build -trimpath -ldflags "-s -w -H windowsgui -X main.version=$Version" -o dist\FVS-Bridge.exe .
    if ($LASTEXITCODE -ne 0) { throw "go build failed" }
} finally {
    Pop-Location
}
$exe = Join-Path $Here "dist\FVS-Bridge.exe"
Write-Host ("Built {0} ({1:N1} MB), version {2}" -f $exe, ((Get-Item $exe).Length / 1MB), $Version)
