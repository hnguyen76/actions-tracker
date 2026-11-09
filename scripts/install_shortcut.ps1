# Tao shortcut "Actions - Cap nhat" tai %USERPROFILE%\Desktop, tro toi scripts\update.ps1
$repo = Split-Path -Parent $PSScriptRoot
$link = Join-Path (Join-Path $env:USERPROFILE 'Desktop') 'Actions - Cap nhat.lnk'
$shell = New-Object -ComObject WScript.Shell
$sc = $shell.CreateShortcut($link)
$sc.TargetPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$sc.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$(Join-Path $repo 'scripts\update.ps1')`""
$sc.WorkingDirectory = $repo
$sc.IconLocation = (Join-Path $env:SystemRoot 'System32\shell32.dll') + ',238'
$sc.Description = 'Lay picks moi tu Action Network va cap nhat dashboard'
$sc.Save()
Write-Host "Da tao: $link"
