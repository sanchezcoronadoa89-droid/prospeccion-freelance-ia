# Arranca el proyecto despues de reiniciar el PC: Docker, Postgres y el dashboard.
# Uso: clic derecho > "Ejecutar con PowerShell", o en una terminal: .\iniciar.ps1
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Test-Docker {
    # Con Docker apagado, "docker ps" escribe un error: no debe detener el script.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        docker ps 2>&1 | Out-Null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    } finally {
        $ErrorActionPreference = $previous
    }
}

Write-Host "1/3  Docker" -ForegroundColor Cyan
if (-not (Test-Docker)) {
    $dockerDesktop = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
    if (-not (Test-Path $dockerDesktop)) { throw "No se encontró Docker Desktop en $dockerDesktop" }
    Start-Process -FilePath $dockerDesktop
    Write-Host "     Abriendo Docker Desktop (puede tardar un par de minutos)..."
    $deadline = (Get-Date).AddMinutes(4)
    while (-not (Test-Docker)) {
        if ((Get-Date) -gt $deadline) { throw "Docker no respondió en 4 minutos. Ábrelo a mano y vuelve a ejecutar este script." }
        Start-Sleep -Seconds 5
    }
}
Write-Host "     Listo."

Write-Host "2/3  Base de datos" -ForegroundColor Cyan
docker compose up -d --wait
if ($LASTEXITCODE -ne 0) { throw "No se pudo arrancar Postgres. Revisa: docker compose logs postgres" }
& .\.venv\Scripts\python.exe -m scripts.db
Write-Host "     Listo."

Write-Host "3/3  Dashboard" -ForegroundColor Cyan
$url = "http://localhost:8000"
$running = $false
try { $running = (Invoke-WebRequest -Uri "$url/api/health" -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200 } catch { }
if (-not $running) {
    # Se abre en su propia ventana: ciérrala para apagar el dashboard.
    Start-Process -FilePath ".\.venv\Scripts\python.exe" `
        -ArgumentList "-m", "uvicorn", "dashboard.api.main:app", "--host", "127.0.0.1", "--port", "8000" `
        -WorkingDirectory $PSScriptRoot
    $deadline = (Get-Date).AddSeconds(40)
    while (-not $running) {
        if ((Get-Date) -gt $deadline) { throw "El dashboard no respondió. Revisa la ventana del servidor." }
        Start-Sleep -Seconds 1
        try { $running = (Invoke-WebRequest -Uri "$url/api/health" -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200 } catch { }
    }
}
Write-Host "     Listo: $url" -ForegroundColor Green
Start-Process $url
