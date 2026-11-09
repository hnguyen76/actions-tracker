# Nut "Actions - Cap nhat": lay picks moi, phan tich, xuat Excel + dashboard, day len GitHub.
$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$dashboard = 'https://hnguyen76.github.io/actions-tracker/'
$python = Join-Path $repo '.venv\Scripts\python.exe'
$stamp = Get-Date -Format 'yyyy-MM-dd HH:mm'

# Run git and print its output as plain text (Windows PowerShell 5.1 shows git's normal stderr as red errors).
function Invoke-Git {
    $out = & git @args 2>&1 | ForEach-Object { "$_" }
    $code = $LASTEXITCODE
    if ($out) { $out | Out-Host }
    return $code
}

function Finish {
    Start-Process $dashboard
    Read-Host 'Nhấn Enter để đóng'
    exit
}

Write-Host "=== Actions - Cập nhật dữ liệu ($stamp) ===" -ForegroundColor Cyan

if (-not (Test-Path $python)) {
    Write-Host "Không tìm thấy Python tại $python — cần cài lại môi trường (.venv)." -ForegroundColor Red
    Finish
}

$branch = (& git rev-parse --abbrev-ref HEAD 2>$null | Out-String).Trim()
$onMain = $branch -eq 'main'
if (-not $onMain) {
    Write-Host "Repo đang ở nhánh '$branch' chứ không phải 'main' — vẫn lấy dữ liệu nhưng sẽ KHÔNG đẩy lên dashboard." -ForegroundColor Yellow
}

if ($onMain -and (Invoke-Git pull --rebase --autostash -q) -ne 0) {
    Write-Host 'Không đồng bộ được với GitHub — vẫn tiếp tục với dữ liệu trên máy.' -ForegroundColor Yellow
}

& $python -m actions_tracker run
$code = $LASTEXITCODE

$changes = & git status --porcelain -- data reports site
if (-not $changes) {
    Write-Host 'Không có dữ liệu mới.'
} elseif (-not $onMain) {
    Write-Host 'Dữ liệu mới chỉ nằm trên máy (không ở nhánh main).' -ForegroundColor Yellow
} else {
    Invoke-Git add -- data reports site | Out-Null
    if ((Invoke-Git commit -q -m "data: update $stamp") -ne 0) {
        Write-Host 'Không commit được dữ liệu mới — xem thông báo git phía trên.' -ForegroundColor Red
    } elseif ((Invoke-Git push -q) -ne 0) {
        Write-Host 'Chưa push được lên GitHub (mất mạng?) — lần bấm sau sẽ push tiếp.' -ForegroundColor Red
    } else {
        Write-Host 'Đã đẩy dữ liệu lên GitHub — dashboard online cập nhật sau 1–2 phút.' -ForegroundColor Green
    }
}

switch ($code) {
    0 { Write-Host 'Cập nhật xong.' -ForegroundColor Green }
    1 { Write-Host 'Tất cả giải đều lỗi (mất mạng hoặc bị chặn) — thử lại sau.' -ForegroundColor Red }
    2 { Write-Host 'Action Network đổi cấu trúc trang — cần sửa parser. Các giải khác vẫn được cập nhật.' -ForegroundColor Red }
    3 { Write-Host 'Có lỗi bất ngờ ở một giải (xem dòng LOI phía trên). Các giải khác vẫn được cập nhật.' -ForegroundColor Red }
    4 { Write-Host 'Dữ liệu đã cập nhật, nhưng file Excel đang mở nên chưa ghi được — đóng Excel rồi bấm lại.' -ForegroundColor Yellow }
    default { Write-Host "Lỗi không mong đợi (mã $code) — xem thông báo phía trên." -ForegroundColor Red }
}

Finish
