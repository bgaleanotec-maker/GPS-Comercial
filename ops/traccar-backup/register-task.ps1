# Programa en Windows la descarga semanal de la copia de Traccar (domingos 07:00, tras el cron del servidor).
# Ejecutar una vez en PowerShell:  .\register-task.ps1
$script = Join-Path $PSScriptRoot "pull-backup.ps1"
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$script`""
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At 7:00am
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2)
Register-ScheduledTask -TaskName "VantiGo - Copia Traccar" -Action $action -Trigger $trigger -Settings $settings -Description "Descarga semanal de la copia de seguridad de Traccar a OneDrive\Traccar_Backups" -Force | Out-Null
Write-Host "Tarea programada 'VantiGo - Copia Traccar' registrada (domingos 07:00; si el PC esta apagado, corre al encenderlo)."
