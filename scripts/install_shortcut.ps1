# Tao shortcut "Actions - Cap nhat" tro toi scripts\update.ps1, tren Desktop cua Windows
# va ca thu muc %USERPROFILE%\Desktop neu Desktop dang bi chuyen huong noi khac.
$repo = Split-Path -Parent $PSScriptRoot
$targets = @([Environment]::GetFolderPath('Desktop'), (Join-Path $env:USERPROFILE 'Desktop')) |
    Where-Object { $_ -and (Test-Path $_) } | Select-Object -Unique
$shell = New-Object -ComObject WScript.Shell
foreach ($dir in $targets) {
    $link = Join-Path $dir 'Actions - Cap nhat.lnk'
    $sc = $shell.CreateShortcut($link)
    $sc.TargetPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $sc.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$(Join-Path $repo 'scripts\update.ps1')`""
    $sc.WorkingDirectory = $repo
    $sc.IconLocation = (Join-Path $env:SystemRoot 'System32\shell32.dll') + ',238'
    $sc.Description = 'Lay picks moi tu Action Network va cap nhat dashboard'
    $sc.Save()
    Write-Host "Da tao: $link"
}
