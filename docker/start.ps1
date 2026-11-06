$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
docker info | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Start Docker Desktop with Linux containers first." }
docker compose up -d --pull missing
if ($LASTEXITCODE -ne 0) { throw "Container startup failed." }
$port = if ($env:GENTACTIX_HTTP_PORT) { $env:GENTACTIX_HTTP_PORT } else { "8080" }
$url = "http://localhost:$port"
for ($i=0; $i -lt 90; $i++) {
  try { $response=Invoke-RestMethod "$url/api/health"; if ($response.status -eq "ok") { Start-Process $url; exit 0 } } catch {}
  Start-Sleep -Seconds 2
}
docker compose logs --tail=80
throw "Startup timed out; inspect container logs."
