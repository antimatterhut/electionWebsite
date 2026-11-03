# Usage (from project root):  .\scripts\start.ps1          -> publish latest outputs, build, serve on :4180
#                             .\scripts\start.ps1 -Full    -> rerun the whole model pipeline first (slow)
param([switch]$Full, [int]$Port = 4180)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$py = ".venv\Scripts\python.exe"

if ($Full) {
    foreach ($s in "fetch","model","ei","crosstab","county","earlyvote","turnout","model","sim","export","overlay") {
        Write-Host "== stage $s"; & $py -m senate.cli run --stage $s
        if ($LASTEXITCODE) { throw "stage $s failed" }
    }
}

& $py -m senate.cli run --stage publish --prev .published --dest site/static/data
if ($LASTEXITCODE) { throw "publish failed" }

# Free the port if an old preview server is holding it (stale servers 404 after a rebuild)
Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }

Set-Location site
npm run build
if ($LASTEXITCODE) { throw "build failed" }
Start-Process "http://localhost:$Port"
npx vite preview --port $Port --strictPort
