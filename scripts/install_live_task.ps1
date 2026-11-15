# Cai lich tu dong (chay 1 lan, PowerShell thuong, khong can quyen admin):
#  - "Actions Live Scores 5m": diem live ESPN moi 5 phut, 09:02-23:59, chi lam viec khi co tran dang da
#  - Chu nhat them khung 09:00-11:00 cho quet day du + Telegram (tran NFL som o London/Duc)
$repo = Split-Path -Parent $PSScriptRoot
$py = Join-Path $repo '.venv\Scripts\pythonw.exe'
$task = Join-Path $repo 'scripts\pc_task.py'
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries `
  -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -MultipleInstances IgnoreNew

$a = New-ScheduledTaskAction -Execute $py -Argument "`"$task`" live" -WorkingDirectory $repo
$t = New-ScheduledTaskTrigger -Daily -At '09:02'
$t.Repetition = (New-ScheduledTaskTrigger -Once -At '09:02' -RepetitionInterval (New-TimeSpan -Minutes 5) `
  -RepetitionDuration (New-TimeSpan -Hours 14 -Minutes 58)).Repetition
Register-ScheduledTask -TaskName 'Actions Live Scores 5m' -Action $a -Trigger $t -Settings $settings `
  -Description 'Diem live (ESPN) moi 5 phut khi co tran dang da' -Force | Out-Null

foreach ($p in @(@{n = 'Actions Update 15m'; m = 15 }, @{n = 'Actions Telegram Alert'; m = 5 })) {
  $existing = Get-ScheduledTask -TaskName $p.n
  $daily = $existing.Triggers | Where-Object { $_.CimClass.CimClassName -eq 'MSFT_TaskDailyTrigger' } | Select-Object -First 1
  $sun = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At '09:00'
  $sun.Repetition = (New-ScheduledTaskTrigger -Once -At '09:00' -RepetitionInterval (New-TimeSpan -Minutes $p.m) `
    -RepetitionDuration (New-TimeSpan -Hours 2)).Repetition
  Set-ScheduledTask -TaskName $p.n -Trigger @($daily, $sun) | Out-Null
}
Get-ScheduledTask -TaskName 'Actions*' | ForEach-Object {
  [pscustomobject]@{ Ten = $_.TaskName; LanToi = (Get-ScheduledTaskInfo $_).NextRunTime }
} | Format-Table -AutoSize
Write-Host 'Da cai xong lich tu dong.' -ForegroundColor Green
