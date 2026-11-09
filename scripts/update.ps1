# Nut "Actions - Cap nhat": lay picks moi, phan tich, xuat Excel + dashboard, day len GitHub.
$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$dashboard = 'https://hnguyen76.github.io/actions-tracker/'
$stamp = Get-Date -Format 'yyyy-MM-dd HH:mm'

Write-Host "=== Actions - Cập nhật dữ liệu ($stamp) ===" -ForegroundColor Cyan

git pull --ff-only 2>&1 | Out-Host
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Không pull được từ GitHub — vẫn tiếp tục với dữ liệu trên máy.' -ForegroundColor Yellow
}

& (Join-Path $repo '.venv\Scripts\python.exe') -m actions_tracker run
$code = $LASTEXITCODE

$changes = git status --porcelain -- data reports site
if ($changes) {
    git add -- data reports site
    git commit -q -m "data: update $stamp"
    git push -q 2>&1 | Out-Host
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'Chưa push được lên GitHub, lần bấm sau sẽ push tiếp.' -ForegroundColor Red
    } else {
        Write-Host 'Đã đẩy dữ liệu lên GitHub — dashboard online cập nhật sau 1–2 phút.' -ForegroundColor Green
    }
} else {
    Write-Host 'Không có dữ liệu mới.'
}

switch ($code) {
    0 { Write-Host 'Cập nhật xong.' -ForegroundColor Green }
    1 { Write-Host 'Tất cả giải đều lỗi (mất mạng hoặc bị chặn) — thử lại sau.' -ForegroundColor Red }
    2 { Write-Host 'Action Network đổi cấu trúc trang — cần sửa parser. Các giải khác vẫn được cập nhật.' -ForegroundColor Red }
    default { Write-Host "Lỗi không mong đợi (mã $code) — xem thông báo phía trên." -ForegroundColor Red }
}

Start-Process $dashboard
Read-Host 'Nhấn Enter để đóng'
