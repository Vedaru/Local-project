<#
.SYNOPSIS
    Project Local - Install Dependencies with Runtime
    使用独立的 Python Runtime 安装项目依赖

.DESCRIPTION
    此脚本使用 GPT-SoVITS/runtime 目录下的独立 Python 3.9 运行时安装所有依赖，
    包括生产环境和开发环境的依赖包。

.PARAMETER Dev
    是否安装开发环境依赖（测试、格式化等工具）

.PARAMETER Mirror
    使用国内镜像源加速下载（清华、阿里云等）

.EXAMPLE
    .\install_dependencies.ps1
    仅安装生产环境依赖

.EXAMPLE
    .\install_dependencies.ps1 -Dev
    安装生产环境和开发环境依赖

.EXAMPLE
    .\install_dependencies.ps1 -Mirror
    使用国内镜像源安装依赖
#>

param(
    [switch]$Dev,
    [switch]$Mirror
)

$ErrorActionPreference = "Stop"

# 获取脚本所在目录（项目根目录）
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RuntimeDir = Join-Path $ProjectDir "runtime"
$PythonExe = Join-Path $RuntimeDir "python.exe"
$PipExe = Join-Path $RuntimeDir "Scripts\pip.exe"

# 检查 runtime Python 是否存在
if (-not (Test-Path $PythonExe)) {
    Write-Host "[错误] 找不到 Python Runtime: $PythonExe" -ForegroundColor Red
    Write-Host "请确保 runtime 目录下包含完整的 Python 3.9 运行时" -ForegroundColor Yellow
    exit 1
}

# 切换到项目目录
Set-Location $ProjectDir

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "Project Local - 依赖安装" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "Python: $PythonExe" -ForegroundColor Green
Write-Host "Pip: $PipExe" -ForegroundColor Green
Write-Host "============================================`n" -ForegroundColor Cyan

# 设置镜像源
$PipIndexUrl = ""
if ($Mirror) {
    $PipIndexUrl = "-i https://pypi.tuna.tsinghua.edu.cn/simple"
    Write-Host "[信息] 使用清华大学镜像源" -ForegroundColor Yellow
}

try {
    # 1. 升级 pip
    Write-Host "[1/4] 升级 pip..." -ForegroundColor Yellow
    & $PythonExe -m pip install --upgrade pip $PipIndexUrl.Split()
    
    if ($LASTEXITCODE -ne 0) {
        throw "升级 pip 失败"
    }
    
    # 2. 安装生产环境依赖
    Write-Host "`n[2/4] 安装生产环境依赖..." -ForegroundColor Yellow
    $RequirementsFile = Join-Path $ProjectDir "requirements.txt"
    & $PipExe install -r $RequirementsFile $PipIndexUrl.Split()
    
    if ($LASTEXITCODE -ne 0) {
        throw "安装生产环境依赖失败"
    }
    
    # 3. 安装 GPT-SoVITS 依赖
    Write-Host "`n[3/4] 检查 GPT-SoVITS 依赖..." -ForegroundColor Yellow
    $SoVITSRequirements = Join-Path $ProjectDir "modules\gpt_sovits\requirements.txt"
    if (Test-Path $SoVITSRequirements) {
        & $PipExe install -r $SoVITSRequirements $PipIndexUrl.Split()
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "GPT-SoVITS 依赖安装失败（非致命错误）"
        }
    } else {
        Write-Host "  未找到 GPT-SoVITS requirements.txt，跳过" -ForegroundColor Gray
    }
    
    # 4. 安装开发环境依赖（可选）
    if ($Dev) {
        Write-Host "`n[4/4] 安装开发环境依赖..." -ForegroundColor Yellow
        $DevPackages = @(
            "pytest>=7.4.0",
            "pytest-cov>=4.1.0",
            "pytest-asyncio>=0.21.0",
            "pytest-mock>=3.12.0",
            "black>=23.0.0",
            "isort>=5.12.0",
            "ruff>=0.1.0",
            "mypy>=1.5.0"
        )
        
        foreach ($package in $DevPackages) {
            & $PipExe install $package $PipIndexUrl.Split()
        }
        
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "部分开发依赖安装失败（非致命错误）"
        }
    } else {
        Write-Host "`n[4/4] 跳过开发环境依赖（使用 -Dev 参数安装）" -ForegroundColor Gray
    }
    
    # 完成
    Write-Host "`n============================================" -ForegroundColor Green
    Write-Host "依赖安装完成！" -ForegroundColor Green
    Write-Host "============================================" -ForegroundColor Green
    Write-Host "`n现在可以运行以下命令启动项目：" -ForegroundColor Cyan
    Write-Host "  .\run_with_runtime.bat" -ForegroundColor Yellow
    Write-Host "  或" -ForegroundColor Cyan
    Write-Host "  .\run_with_runtime.ps1" -ForegroundColor Yellow
    Write-Host "============================================`n" -ForegroundColor Green
    
} catch {
    Write-Host "`n[错误] $_" -ForegroundColor Red
    Write-Host "依赖安装失败，请检查错误信息" -ForegroundColor Red
    exit 1
}
