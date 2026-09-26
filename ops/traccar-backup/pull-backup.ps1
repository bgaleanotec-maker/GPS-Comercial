# Descarga al PC la ultima copia de Traccar (semanal, via scp) y verifica su integridad.
# Destino: OneDrive (asi queda ademas una copia en la nube de Microsoft).
param(
    [string]$ServerIp = "64.227.85.213",
    [string]$Dest = "$env:USERPROFILE\OneDrive\Traccar_Backups",
    [string]$Key = "$env:USERPROFILE\.ssh\vantigo_traccar",
    [int]$KeepLocal = 12
)
$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force $Dest | Out-Null
$log = Join-Path $Dest "pull.log"
function Log($m) { $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $m"; Add-Content -Path $log -Value $line -Encoding utf8; Write-Host $line }

try {
    $sshOpts = @("-i", $Key, "-o", "StrictHostKeyChecking=accept-new", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20")
    $name = (& ssh @sshOpts "root@$ServerIp" "readlink -f /opt/traccar-backups/latest.tar.gz").Trim()
    if (-not $name) { throw "El servidor no tiene copias aun (latest.tar.gz no existe)" }
    $file = Split-Path $name -Leaf
    $local = Join-Path $Dest $file
    if (Test-Path $local) { Log "Ya descargada: $file"; }
    else {
        Log "Descargando $file ..."
        & scp @sshOpts "root@${ServerIp}:$name" "$local"
        & scp @sshOpts "root@${ServerIp}:$name.sha256" "$local.sha256"
        $expected = (Get-Content "$local.sha256" -First 1).Split(' ')[0].ToLower()
        $actual = (Get-FileHash $local -Algorithm SHA256).Hash.ToLower()
        if ($expected -ne $actual) { Remove-Item $local -Force; throw "Checksum no coincide, descarga descartada" }
        Log ("OK {0} ({1:N1} MB) verificada" -f $file, ((Get-Item $local).Length / 1MB))
    }
    # Rotacion local: conservar las ultimas $KeepLocal copias descargadas
    Get-ChildItem $Dest -Filter "traccar-backup-*.tar.gz" | Sort-Object LastWriteTime -Descending |
        Select-Object -Skip $KeepLocal | ForEach-Object { Remove-Item $_.FullName -Force; Remove-Item "$($_.FullName).sha256" -Force -ErrorAction SilentlyContinue; Log "rotada local: $($_.Name)" }
} catch {
    Log "ERROR: $($_.Exception.Message)"
    exit 1
}
