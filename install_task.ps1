# Script para instalar la sincronización como Tarea Programada de Windows

$TaskName = "NexusSync_Service"
$PythonW = "C:\Users\Ruben\AppData\Local\Programs\Python\Python313\pythonw.exe"
$ScriptPath = Join-Path (Get-Location) "main.py"
$WorkingDirectory = Get-Location
$IntervalMinutes = 5

# 1. Crear la Acción (Ejecutar pythonw.exe con el script)
$Action = New-ScheduledTaskAction -Execute $PythonW -Argument "`"$ScriptPath`"" -WorkingDirectory $WorkingDirectory

# 2. Crear el Disparador (Cada 5 minutos indefinidamente)
$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)

# 3. Configuraciones adicionales (Reintentar si falla, permitir ejecución en paralelo si se traba, etc.)
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances Parallel

# 4. Registrar la tarea (Se recomienda ejecutar PowerShell como Administrador)
try {
    # Intentar eliminar si ya existe para actualizar
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "Sincronización automatizada de Nexus (Sin consola)"
    
    Write-Host "`n[ OK ] Tarea '$TaskName' creada exitosamente." -ForegroundColor Green
    Write-Host "Frecuencia: Cada $IntervalMinutes minutos."
    Write-Host "Modo: Invisible (Sin consola)."
    Write-Host "Puedes monitorearla en el 'Programador de Tareas'."
} catch {
    Write-Host "`n[ ERROR ] No se pudo crear la tarea. Asegúrate de ejecutar este comando como ADMINISTRADOR." -ForegroundColor Red
    Write-Host $_.Exception.Message
}
