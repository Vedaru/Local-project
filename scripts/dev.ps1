# Project Local - Development Scripts
# PowerShell helper scripts for Windows developers

# Usage: .\scripts\dev.ps1 <command>
# Commands: setup, test, lint, format, check, clean

param(
    [Parameter(Position=0)]
    [string]$Command = "help"
)

$ErrorActionPreference = "Stop"

function Show-Help {
    Write-Host @"
Project Local - Development Commands
====================================

Usage: .\scripts\dev.ps1 <command>

Commands:
  setup       Install all dependencies (dev + prod)
  test        Run all tests
  test-cov    Run tests with coverage report
  lint        Run all linters (ruff, mypy)
  format      Format code with black and isort
  check       Run all checks (lint + test)
  clean       Clean build artifacts and caches
  pre-commit  Install and run pre-commit hooks
  help        Show this help message

Examples:
  .\scripts\dev.ps1 setup
  .\scripts\dev.ps1 test
  .\scripts\dev.ps1 format

"@
}

function Install-Dependencies {
    Write-Host "Installing dependencies..." -ForegroundColor Cyan
    
    # Install production dependencies
    pip install -r requirements.txt
    
    # Install dev dependencies
    pip install pytest pytest-cov pytest-asyncio pytest-mock
    pip install black isort ruff mypy
    pip install pre-commit
    
    Write-Host "Dependencies installed!" -ForegroundColor Green
}

function Run-Tests {
    Write-Host "Running tests..." -ForegroundColor Cyan
    pytest tests/ -v --tb=short
}

function Run-TestsCov {
    Write-Host "Running tests with coverage..." -ForegroundColor Cyan
    pytest tests/ --cov=modules --cov-report=html --cov-report=term -v
    Write-Host "Coverage report generated in htmlcov/" -ForegroundColor Green
}

function Run-Lint {
    Write-Host "Running linters..." -ForegroundColor Cyan
    
    Write-Host "Running ruff..." -ForegroundColor Yellow
    ruff check modules/ tests/ main.py
    
    Write-Host "Running mypy..." -ForegroundColor Yellow
    mypy modules/ --ignore-missing-imports
    
    Write-Host "Lint checks passed!" -ForegroundColor Green
}

function Format-Code {
    Write-Host "Formatting code..." -ForegroundColor Cyan
    
    Write-Host "Running black..." -ForegroundColor Yellow
    black modules/ tests/ main.py
    
    Write-Host "Running isort..." -ForegroundColor Yellow
    isort modules/ tests/ main.py
    
    Write-Host "Code formatted!" -ForegroundColor Green
}

function Run-AllChecks {
    Write-Host "Running all checks..." -ForegroundColor Cyan
    
    Format-Code
    Run-Lint
    Run-Tests
    
    Write-Host "All checks passed!" -ForegroundColor Green
}

function Clean-Artifacts {
    Write-Host "Cleaning build artifacts..." -ForegroundColor Cyan
    
    # Remove Python cache
    Get-ChildItem -Path . -Include "__pycache__" -Recurse -Directory | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    Get-ChildItem -Path . -Include "*.pyc" -Recurse | Remove-Item -Force -ErrorAction SilentlyContinue
    
    # Remove test/coverage artifacts
    Remove-Item -Path ".pytest_cache" -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -Path "htmlcov" -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -Path ".coverage" -Force -ErrorAction SilentlyContinue
    Remove-Item -Path "coverage.xml" -Force -ErrorAction SilentlyContinue
    
    # Remove build artifacts
    Remove-Item -Path "dist" -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -Path "build" -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -Path "*.egg-info" -Recurse -Force -ErrorAction SilentlyContinue
    
    # Remove mypy cache
    Remove-Item -Path ".mypy_cache" -Recurse -Force -ErrorAction SilentlyContinue
    
    # Remove ruff cache
    Remove-Item -Path ".ruff_cache" -Recurse -Force -ErrorAction SilentlyContinue
    
    Write-Host "Clean complete!" -ForegroundColor Green
}

function Setup-PreCommit {
    Write-Host "Setting up pre-commit hooks..." -ForegroundColor Cyan
    
    pre-commit install
    pre-commit run --all-files
    
    Write-Host "Pre-commit hooks installed!" -ForegroundColor Green
}

# Main switch
switch ($Command.ToLower()) {
    "setup" { Install-Dependencies }
    "test" { Run-Tests }
    "test-cov" { Run-TestsCov }
    "lint" { Run-Lint }
    "format" { Format-Code }
    "check" { Run-AllChecks }
    "clean" { Clean-Artifacts }
    "pre-commit" { Setup-PreCommit }
    "help" { Show-Help }
    default {
        Write-Host "Unknown command: $Command" -ForegroundColor Red
        Show-Help
        exit 1
    }
}
