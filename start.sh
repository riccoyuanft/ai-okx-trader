#!/bin/bash
# AI OKX Trader — 一键环境检查 + 启动脚本 (Linux/Mac)

set -e

BOLD="\033[1m"
GREEN="\033[0;32m"
YELLOW="\033[0;33m"
RED="\033[0;31m"
RESET="\033[0m"

echo -e "${BOLD}============================================${RESET}"
echo -e "${BOLD}  AI OKX Trader — 启动检查${RESET}"
echo -e "${BOLD}============================================${RESET}"

# ── 1. Python 版本检查 ──────────────────────────────────────
echo -e "\n${BOLD}[1/4] 检查 Python 版本...${RESET}"
if ! command -v python3 &>/dev/null; then
    echo -e "${RED}✗ 未找到 python3，请安装 Python 3.11+${RESET}"
    exit 1
fi

PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PYTHON_MAJOR=$(python3 -c "import sys; print(sys.version_info.major)")
PYTHON_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")

if [ "$PYTHON_MAJOR" -lt 3 ] || { [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 11 ]; }; then
    echo -e "${RED}✗ Python 版本 ${PYTHON_VERSION} 不满足要求（需要 3.11+）${RESET}"
    exit 1
fi
echo -e "${GREEN}✓ Python ${PYTHON_VERSION}${RESET}"

# ── 2. 虚拟环境 ────────────────────────────────────────────
echo -e "\n${BOLD}[2/4] 检查虚拟环境...${RESET}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ ! -d "$SCRIPT_DIR/.venv" ]; then
    echo -e "${YELLOW}  未找到 .venv，正在创建...${RESET}"
    python3 -m venv "$SCRIPT_DIR/.venv"
    echo -e "${GREEN}✓ 虚拟环境已创建${RESET}"
fi

source "$SCRIPT_DIR/.venv/bin/activate"

# 检查依赖是否已安装
if ! python -c "import pandas_ta" &>/dev/null; then
    echo -e "${YELLOW}  依赖未安装，正在执行 pip install...${RESET}"
    pip install -r "$SCRIPT_DIR/requirements.txt" --quiet
    echo -e "${GREEN}✓ 依赖安装完成${RESET}"
else
    echo -e "${GREEN}✓ 虚拟环境就绪${RESET}"
fi

# ── 3. 配置文件检查 ─────────────────────────────────────────
echo -e "\n${BOLD}[3/4] 检查配置文件...${RESET}"
if [ ! -f "$SCRIPT_DIR/.env" ]; then
    echo -e "${YELLOW}  未找到 .env，正在从模板复制...${RESET}"
    cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/.env"
    echo -e "${RED}"
    echo -e "  ┌─────────────────────────────────────────────────┐"
    echo -e "  │  请先编辑 .env 文件，填写以下必填项：            │"
    echo -e "  │                                                  │"
    echo -e "  │  OKX_SIMULATED_API_KEY  (模拟盘 API Key)        │"
    echo -e "  │  OKX_SIMULATED_SECRET_KEY                       │"
    echo -e "  │  OKX_SIMULATED_PASSPHRASE                       │"
    echo -e "  │  AI_PROVIDER + 对应的 API Key                   │"
    echo -e "  └─────────────────────────────────────────────────┘"
    echo -e "${RESET}"
    echo -e "  配置完成后重新运行此脚本。"
    exit 0
fi

# 检查关键配置项是否仍为占位符
if grep -q "your_simulated_api_key\|your_real_api_key\|sk-your_qwen" "$SCRIPT_DIR/.env" 2>/dev/null; then
    echo -e "${RED}✗ .env 中仍有未填写的占位符，请编辑 .env 文件填写真实 API Key${RESET}"
    exit 1
fi
echo -e "${GREEN}✓ 配置文件就绪${RESET}"

# ── 4. Redis 检查（可选） ────────────────────────────────────
echo -e "\n${BOLD}[4/4] 检查 Redis（可选）...${RESET}"
USE_REDIS=$(grep -E "^USE_REDIS=" "$SCRIPT_DIR/.env" 2>/dev/null | cut -d= -f2 | tr -d '[:space:]"')
if [ "$USE_REDIS" = "true" ]; then
    if command -v redis-cli &>/dev/null && redis-cli ping &>/dev/null 2>&1; then
        echo -e "${GREEN}✓ Redis 连接正常${RESET}"
    else
        echo -e "${YELLOW}⚠ Redis 未运行，但 USE_REDIS=true。建议先启动 Redis，或设置 USE_REDIS=false${RESET}"
    fi
else
    echo -e "${YELLOW}  Redis 未启用（USE_REDIS=false），持仓状态将使用本地 JSON 文件${RESET}"
fi

# ── 启动 ──────────────────────────────────────────────────
echo -e "\n${BOLD}============================================${RESET}"
echo -e "${GREEN}${BOLD}  所有检查通过，正在启动交易机器人...${RESET}"
echo -e "${BOLD}============================================${RESET}\n"

cd "$SCRIPT_DIR"
exec python -m src.main
