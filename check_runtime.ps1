<#
.SYNOPSIS
    Runtime Health Check - 检查 Runtime 环境是否配置正确

.DESCRIPTION
    此脚本检查项目的独立 Python Runtime 配置是否完整和正确，
    包括文件完整性、路径配置、依赖安装等。

.EXAMPLE
    .\check_runtime.ps1
#>

$ErrorActionPreference = "Continue"

# 配置
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RuntimeDir = Join-Path $ProjectDir "runtime"
$PythonExe = Join-Path $RuntimeDir "python.exe"
$PipExe = Join-Path $RuntimeDir "Scripts\pip.exe"
$PthFile = Join-Path $RuntimeDir "python39._pth"

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "Project Local - Runtime 健康检查" -ForegroundColor Cyan
Write-Host "============================================`n" -ForegroundColor Cyan

$AllChecks = @()
$PassedChecks = 0
$TotalChecks = 0

function Test-Check {
    param(
        [string]$Name,
        [bool]$Result,
        [string]$SuccessMsg = "✓ 通过",
        [string]$FailMsg = "✗ 失败",
        [string]$Hint = ""
    )
    
    $script:TotalChecks++
    
    if ($Result) {
        Write-Host "[$SuccessMsg] $Name" -ForegroundColor Green
        $script:PassedChecks++
        return $true
    } else {
        Write-Host "[$FailMsg] $Name" -ForegroundColor Red
        if ($Hint) {
            Write-Host "  提示: $Hint" -ForegroundColor Yellow
        }
        return $false
    }
}

# 检查 1: Runtime 目录存在
Write-Host "[检查 1/8] Runtime 目录..." -ForegroundColor Yellow
Test-Check -Name "Runtime 目录存在" `
    -Result (Test-Path $RuntimeDir) `
    -Hint "请确保 runtime 目录存在"

# 检查 2: Python 可执行文件
Write-Host "`n[检查 2/8] Python 解释器..." -ForegroundColor Yellow
Test-Check -Name "python.exe 存在" `
    -Result (Test-Path $PythonExe) `
    -Hint "缺少 Python 解释器，请获取完整的 runtime"

if (Test-Path $PythonExe) {
    try {
        $PyVersion = & $PythonExe --version 2>&1
        Test-Check -Name "Python 版本: $PyVersion" -Result $true
    } catch {
        Test-Check -Name "Python 可执行" -Result $false -Hint "Python 解释器无法运行"
    }
}

# 检查 3: Pip 包管理器
Write-Host "`n[检查 3/8] Pip 包管理器..." -ForegroundColor Yellow
Test-Check -Name "pip.exe 存在" `
    -Result (Test-Path $PipExe) `
    -Hint "缺少 pip，运行: python.exe -m ensurepip"

if (Test-Path $PipExe) {
    try {
        $PipVersion = & $PipExe --version 2>&1
        Test-Check -Name "Pip 版本: $($PipVersion -split ' ' | Select-Object -First 2 -Join ' ')" -Result $true
    } catch {
        Test-Check -Name "Pip 可执行" -Result $false
    }
}

# 检查 4: python._pth 配置
Write-Host "`n[检查 4/8] Python 路径配置..." -ForegroundColor Yellow
$PthExists = Test-Check -Name "python39._pth 存在" `
    -Result (Test-Path $PthFile) `
    -Hint "缺少路径配置文件"

if ($PthExists) {
    $PthContent = Get-Content $PthFile -Raw
    Test-Check -Name "包含 import site" `
        -Result ($PthContent -match "import site") `
        -Hint "需要启用 site-packages 支持"
    
    Test-Check -Name "包含项目路径" `
        -Result ($PthContent -match "\\.\\.\\") `
        -Hint "需要添加项目根目录到路径"
}

# 检查 5: 关键依赖
Write-Host "`n[检查 5/8] 核心依赖包..." -ForegroundColor Yellow
if (Test-Path $PipExe) {
    $InstalledPackages = & $PipExe list 2>&1 | Out-String
    
    $RequiredPackages = @(
        @{Name="openai"; Display="OpenAI SDK"},
        @{Name="PyQt6"; Display="PyQt6"},
        @{Name="chromadb"; Display="ChromaDB"},
        @{Name="requests"; Display="Requests"}
    )
    
    foreach ($pkg in $RequiredPackages) {
        $installed = $InstalledPackages -match $pkg.Name
        Test-Check -Name "$($pkg.Display)" `
            -Result $installed `
            -SuccessMsg "✓" `
            -FailMsg "✗" `
            -Hint "运行 install_dependencies.ps1 安装依赖"
    }
} else {
    Write-Host "  跳过（pip 不可用）" -ForegroundColor Gray
}

# 检查 6: Python 可以导入项目模块
Write-Host "`n[检查 6/8] 模块导入测试..." -ForegroundColor Yellow
if (Test-Path $PythonExe) {
    Set-Location $ProjectDir
    
    # 测试导入 modules
    $TestImport = @"
import sys
try:
    import modules
    print('OK')
except Exception as e:
    print(f'ERROR: {e}')
"@
    
    $ImportResult = & $PythonExe -c $TestImport 2>&1
    Test-Check -Name "导入 modules 包" `
        -Result ($ImportResult -eq "OK") `
        -Hint "检查 python39._pth 配置是否包含项目路径"
}

# 检查 7: 项目文件完整性
Write-Host "`n[检查 7/8] 项目文件..." -ForegroundColor Yellow
$ProjectFiles = @(
    @{Path="main.py"; Name="主入口文件"},
    @{Path="config.yaml"; Name="配置文件"},
    @{Path="requirements.txt"; Name="依赖列表"},
    @{Path="modules\__init__.py"; Name="modules 包"}
)

foreach ($file in $ProjectFiles) {
    $FilePath = Join-Path $ProjectDir $file.Path
    Test-Check -Name $file.Name `
        -Result (Test-Path $FilePath) `
        -SuccessMsg "✓" `
        -FailMsg "✗"
}

# 检查 8: 启动脚本
Write-Host "`n[检查 8/8] 启动脚本..." -ForegroundColor Yellow
Test-Check -Name "run_with_runtime.ps1" `
    -Result (Test-Path (Join-Path $ProjectDir "run_with_runtime.ps1")) `
    -SuccessMsg "✓" `
    -FailMsg "✗"

Test-Check -Name "install_dependencies.ps1" `
    -Result (Test-Path (Join-Path $ProjectDir "install_dependencies.ps1")) `
    -SuccessMsg "✓" `
    -FailMsg "✗"

# 总结
Write-Host "`n============================================" -ForegroundColor Cyan
Write-Host "检查完成" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan

$SuccessRate = [math]::Round(($PassedChecks / $TotalChecks) * 100, 1)
$StatusColor = if ($SuccessRate -eq 100) { "Green" } elseif ($SuccessRate -ge 70) { "Yellow" } else { "Red" }

Write-Host "`n通过: $PassedChecks / $TotalChecks ($SuccessRate%)" -ForegroundColor $StatusColor

if ($PassedChecks -eq $TotalChecks) {
    Write-Host "`n✓ Runtime 环境配置正确，可以启动项目！" -ForegroundColor Green
    Write-Host "  运行: .\run_with_runtime.ps1" -ForegroundColor Cyan
} elseif ($SuccessRate -ge 70) {
    Write-Host "`n⚠ Runtime 环境部分配置有问题，建议修复后使用" -ForegroundColor Yellow
    Write-Host "  如果缺少依赖，运行: .\install_dependencies.ps1" -ForegroundColor Cyan
} else {
    Write-Host "`n✗ Runtime 环境配置有严重问题，请按提示修复" -ForegroundColor Red
    Write-Host "  参考文档: RUNTIME.md" -ForegroundColor Cyan
}

Write-Host "`n============================================`n" -ForegroundColor Cyan
