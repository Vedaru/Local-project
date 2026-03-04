<#
.SYNOPSIS
    Project Local - Runtime Launcher (PowerShell)
    使用独立的 Python Runtime 启动项目

.DESCRIPTION
    此脚本使用 GPT-SoVITS/runtime 目录下的独立 Python 3.9 运行时启动项目，
    避免与系统 Python 环境冲突。

.PARAMETER Arguments
    传递给 main.py 的额外参数

.EXAMPLE
    .\run_with_runtime.ps1
    .\run_with_runtime.ps1 --debug
#>

param(
    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$Arguments
)

$ErrorActionPreference = "Stop"

# 获取脚本所在目录（项目根目录）
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RuntimeDir = Join-Path $ProjectDir "runtime"
$PythonExe = Join-Path $RuntimeDir "python.exe"

# 检查 runtime Python 是否存在
if (-not (Test-Path $PythonExe)) {
    Write-Host "[错误] 找不到 Python Runtime: $PythonExe" -ForegroundColor Red
    Write-Host "请确保 runtime 目录下包含完整的 Python 3.9 运行时" -ForegroundColor Yellow
    exit 1
}

# 设置环境变量
$env:CT2_USE_CUDA = "0"
if (-not $env:LOKY_MAX_CPU_COUNT) {
    $env:LOKY_MAX_CPU_COUNT = (Get-CimInstance -ClassName Win32_Processor | 
        Measure-Object -Property NumberOfLogicalProcessors -Sum).Sum
}

# 切换到项目目录
Set-Location $ProjectDir

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "Project Local - 使用独立 Runtime 启动" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "Python: $PythonExe" -ForegroundColor Green
Write-Host "项目目录: $ProjectDir" -ForegroundColor Green
Write-Host "============================================`n" -ForegroundColor Cyan

# 启动主程序
$MainScript = Join-Path $ProjectDir "main.py"
& $PythonExe $MainScript $Arguments

if ($LASTEXITCODE -ne 0) {
    Write-Host "`n[错误] 程序执行失败，错误代码: $LASTEXITCODE" -ForegroundColor Red
    exit $LASTEXITCODE
}
