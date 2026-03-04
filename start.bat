@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion

echo ============================================
echo   AI OKX Trader -- 启动检查
echo ============================================

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

:: ── 1. Python 版本检查 ──────────────────────────────────────
echo.
echo [1/4] 检查 Python 版本...

python --version >nul 2>&1
if errorlevel 1 (
    echo   [错误] 未找到 python，请安装 Python 3.11+ 并添加到 PATH
    pause
    exit /b 1
)

for /f "tokens=2" %%v in ('python --version 2^>^&1') do set "PY_VER=%%v"
for /f "tokens=1,2 delims=." %%a in ("%PY_VER%") do (
    set "PY_MAJOR=%%a"
    set "PY_MINOR=%%b"
)

if %PY_MAJOR% LSS 3 (
    echo   [错误] Python %PY_VER% 不满足要求（需要 3.11+）
    pause
    exit /b 1
)
if %PY_MAJOR% EQU 3 if %PY_MINOR% LSS 11 (
    echo   [错误] Python %PY_VER% 不满足要求（需要 3.11+）
    pause
    exit /b 1
)
echo   [OK] Python %PY_VER%

:: ── 2. 虚拟环境 ────────────────────────────────────────────
echo.
echo [2/4] 检查虚拟环境...

if not exist "%SCRIPT_DIR%\.venv" (
    echo   未找到 .venv，正在创建...
    python -m venv "%SCRIPT_DIR%\.venv"
    if errorlevel 1 (
        echo   [错误] 创建虚拟环境失败
        pause
        exit /b 1
    )
    echo   虚拟环境已创建
)

call "%SCRIPT_DIR%\.venv\Scripts\activate.bat"

:: 检查 pandas_ta 是否已安装
python -c "import pandas_ta" >nul 2>&1
if errorlevel 1 (
    echo   依赖未安装，正在执行 pip install...
    pip install -r "%SCRIPT_DIR%\requirements.txt" --quiet
    if errorlevel 1 (
        echo   [错误] 依赖安装失败，请检查网络或手动运行: pip install -r requirements.txt
        pause
        exit /b 1
    )
    echo   [OK] 依赖安装完成
) else (
    echo   [OK] 虚拟环境就绪
)

:: ── 3. 配置文件检查 ─────────────────────────────────────────
echo.
echo [3/4] 检查配置文件...

if not exist "%SCRIPT_DIR%\.env" (
    echo   未找到 .env，正在从模板复制...
    copy "%SCRIPT_DIR%\.env.example" "%SCRIPT_DIR%\.env" >nul
    echo.
    echo   ┌─────────────────────────────────────────────────┐
    echo   │  请先编辑 .env 文件，填写以下必填项：            │
    echo   │                                                  │
    echo   │  OKX_SIMULATED_API_KEY  (模拟盘 API Key)        │
    echo   │  OKX_SIMULATED_SECRET_KEY                       │
    echo   │  OKX_SIMULATED_PASSPHRASE                       │
    echo   │  AI_PROVIDER + 对应的 API Key                   │
    echo   └─────────────────────────────────────────────────┘
    echo.
    echo   配置完成后重新运行此脚本。
    start notepad "%SCRIPT_DIR%\.env"
    pause
    exit /b 0
)

:: 检查是否仍有占位符
findstr /C:"your_simulated_api_key" /C:"your_real_api_key" /C:"sk-your_qwen" "%SCRIPT_DIR%\.env" >nul 2>&1
if not errorlevel 1 (
    echo   [错误] .env 中仍有未填写的占位符，请编辑 .env 文件填写真实 API Key
    start notepad "%SCRIPT_DIR%\.env"
    pause
    exit /b 1
)
echo   [OK] 配置文件就绪

:: ── 4. Redis 检查（可选） ────────────────────────────────────
echo.
echo [4/4] 检查 Redis（可选）...

for /f "tokens=2 delims==" %%v in ('findstr /B "USE_REDIS=" "%SCRIPT_DIR%\.env" 2^>nul') do set "USE_REDIS=%%v"
set "USE_REDIS=%USE_REDIS: =%"

if /i "%USE_REDIS%"=="true" (
    where redis-cli >nul 2>&1
    if not errorlevel 1 (
        redis-cli ping >nul 2>&1
        if not errorlevel 1 (
            echo   [OK] Redis 连接正常
        ) else (
            echo   [警告] Redis 未运行，但 USE_REDIS=true
            echo          建议先启动 Redis，或设置 USE_REDIS=false
        )
    ) else (
        echo   [警告] 未找到 redis-cli，无法验证 Redis 状态
    )
) else (
    echo   Redis 未启用，持仓状态将使用本地 JSON 文件
)

:: ── 启动 ──────────────────────────────────────────────────
echo.
echo ============================================
echo   所有检查通过，正在启动交易机器人...
echo ============================================
echo.

cd /d "%SCRIPT_DIR%"
python -m src.main

pause
