# AI OKX Trader

基于 AI 大模型的 OKX 现货自动化交易系统，支持 GPT-4o / 通义千问 / 豆包，只做多、不杠杆。

## 📋 项目概述

AI 作为全职交易员，根据 OKX K 线数据和 pandas-ta 技术指标自主决策建仓，系统通过独立的价格监控线程（每秒读取价格）执行止损止盈，并通过钉钉发送实时通知。

**核心特性：**
- 🤖 **AI 决策**: 开仓 / 平仓 / 观望，自主设定入场价、止损止盈位
- 📊 **技术指标**: MA / EMA / MACD / RSI / BOLL / ATR（5m、15m、1H 三个周期，基于 pandas-ta）
- 🔍 **实时价格监控**: 独立线程每秒读取价格，触发止损止盈自动平仓
- 📈 **追踪止损**: 浮盈到位后自动上移止损，阶梯锁定利润
- 🔄 **多标的轮动**: 支持标的池，AI 空仓时自动扫描切换最优标的
- 🎯 **自动筛选标的**: 每 2 小时自动筛选全市场，动态更新标的池（可选）
- 💾 **状态持久化**: 持仓状态写入 Redis / 本地 JSON，重启自动恢复
- 🔔 **钉钉通知**: 建仓、止盈、止损、风控触发均有推送
- ⚙️ **可配置策略系统**: 支持 YAML 策略文件，通过 `.env` 一键切换策略，23 个参数全面可配置
- 🔒 **风控**: 日亏损限额自动停机、连续亏损降仓

## 🏗️ 系统架构

```
TradingBot (main.py)
├── 交易决策循环 (APScheduler, 每5分钟/15分钟)
│   ├── OKXClient        — K线、持仓、下单、撤单
│   ├── TACalculator     — pandas-ta 技术指标
│   ├── AIAgent          — AI 决策 (OpenAI 兼容接口)
│   ├── RiskManager      — 风控校验
│   └── SymbolPoolManager — 标的池轮动
└── 价格监控线程 (每秒)
    ├── 触发止损 → 撤 TP 挂单 → 市价平仓
    ├── 追踪止损 → 逐步上移 SL
    └── 检查 TP 挂单成交状态
```

**技术栈：**
- Python 3.11+, APScheduler, loguru, pydantic
- python-okx（OKX 官方 SDK）
- openai（兼容通义千问/豆包）
- pandas-ta（技术指标）
- Redis（可选，状态持久化 + 交易历史）

## 📁 项目结构

```
ai-okx-trader/
├── src/
│   ├── main.py                   # 主控制器（交易循环 + 价格监控线程）
│   ├── config/
│   │   ├── settings.py           # 配置管理（pydantic）
│   │   ├── prompts.py            # AI 系统提示词 + 市场数据格式化
│   │   └── strategy_loader.py    # 策略配置加载器
│   ├── data/
│   │   ├── models.py             # 数据模型（MarketData / Position / AIDecision）
│   │   ├── okx_client.py         # OKX API 封装
│   │   ├── position_state.py     # 持仓状态本地 JSON 持久化
│   │   ├── redis_state.py        # Redis 状态管理（持仓/历史/开关）
│   │   └── symbol_pool_manager.py # 标的池动态管理
│   ├── ai/
│   │   └── agent.py              # AI 决策器（历史摘要 + 多提供商）
│   ├── indicators/
│   │   └── ta_calculator.py      # pandas-ta 指标计算（MA/EMA/MACD/RSI/BOLL/ATR）
│   ├── risk/
│   │   └── manager.py            # 风控（盈亏比、日限额、连续亏损）
│   ├── notify/
│   │   └── dingtalk.py           # 钉钉机器人通知
│   └── monitor/
│       └── logger.py             # loguru 日志配置
├── strategies/                   # 策略配置文件目录（YAML格式）
│   ├── 15m_trend_following.yaml  # 15分钟短线趋势跟随策略（默认）
│   ├── 5m_scalping.yaml          # 5分钟超短线剥头皮策略
│   └── 1h_swing.yaml             # 1小时波段交易策略
├── scripts/
│   ├── symbol_screener.py        # 标的筛选脚本（基于 1H+5m 趋势评分）
│   └── set_stop_loss.py          # 手动设置止损止盈工具
├── tests/                        # 功能测试脚本
├── docs/                         # 详细功能文档
├── deployment/                   # Dockerfile + docker-compose + systemd
├── logs/                         # 运行日志（自动创建）
├── .env.example                  # 基础配置模板
├── .env.strategy.example         # 策略参数模板
└── requirements.txt              # Python 依赖
```

## 🚀 快速开始

### 前置要求

- Python 3.11+
- OKX 账户（先用**模拟盘**测试，无需真实资金）
- AI API Key：千问 / OpenAI / 豆包（国内推荐），三选一

### 第一步：安装依赖

```bash
git clone <repository-url>
cd ai-okx-trader

python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/Mac

pip install -r requirements.txt
```

> `requirements.txt` 已包含 `pandas-ta`（技术指标库），无需额外安装 TA-Lib C 库。

### 第二步：获取 API Key

**OKX 模拟盘（强烈建议先用）：**
1. 登录 [OKX](https://www.okx.com) → **交易 → 模拟交易**
2. 个人中心 → **创建模拟盘 APIKey**，权限选**只读 + 交易**（禁止提现）

**AI API Key（通义千问示例）：**
1. 登录 [火山引擎](https://console.volcengine.com/home) → 火山方舟 → API Key管理 → 创建

### 第三步：配置

```bash
copy .env.example .env        # Windows
# cp .env.example .env        # Linux/Mac
```

编辑 `.env`，**至少填写以下必填项**：

```env
# OKX API — 模拟盘/实盘各一套，通过 OKX_TESTNET 切换
OKX_SIMULATED_API_KEY=your_simulated_api_key
OKX_SIMULATED_SECRET_KEY=your_simulated_secret_key
OKX_SIMULATED_PASSPHRASE=your_simulated_passphrase
OKX_TESTNET=true              # true=模拟盘，false=实盘

# AI（三选一）
AI_PROVIDER=qwen
QWEN_API_KEY=sk-your_qwen_api_key

# 策略选择（可选：15m_trend_following / 5m_scalping / 1h_swing）
STRATEGY_NAME=15m_trend_following

# 交易配置
SYMBOL_POOL=BTC-USDT,ETH-USDT,SOL-USDT
INITIAL_CAPITAL=1000.0
```

> 两套 API Key 同时配置好后，切换模式只需改 `OKX_TESTNET` 的值，无需重填密钥。详见 [模拟盘与实盘配置.md](docs/模拟盘与实盘配置.md)。

### 第四步：运行

手动启动：

```bash
python -m src.main
```

启动后输出示例：

```
AI OKX Trader Started | Symbol: BTC-USDT | Testnet: True
✓ 历史K线数据已加载到AI记忆
🔍 价格监控线程已启动 (自动止损止盈)
```

之后每 5 分钟（无持仓时 15 分钟）触发一次 AI 决策，按 `Ctrl+C` 安全退出。

### 可选配置

**启用 Redis（推荐，用于持仓恢复和交易历史）：**

```bash
# Windows: https://github.com/tporadowski/redis/releases
# Linux: sudo apt-get install redis-server && redis-server
# Mac: brew install redis && redis-server
```

```env
USE_REDIS=true
REDIS_HOST=localhost
REDIS_PORT=6379
```

**启用钉钉通知：**

```env
DINGTALK_ENABLED=true
DINGTALK_WEBHOOK=https://oapi.dingtalk.com/robot/send?access_token=YOUR_TOKEN
DINGTALK_SECRET=YOUR_SECRET
```

**标的池配置（两种模式）：**

```env
# 模式1：自动筛选（推荐，默认启用）
ENABLE_AUTO_SCREENING=true
SYMBOL_POOL=BTC-USDT,ETH-USDT,SOL-USDT  # 作为降级方案

# 模式2：静态配置
ENABLE_AUTO_SCREENING=false
SYMBOL_POOL=BTC-USDT,ETH-USDT,SOL-USDT  # 作为主配置
```

**自动筛选说明**：
- 启用后，系统每 2 小时自动运行 `symbol_screener.py` 筛选全市场标的
- 根据技术指标（1H 趋势 + 5m 时机）自动评分，高评分（≥60）进主池
- 筛选结果存储在 Redis，**覆盖** `SYMBOL_POOL` 配置
- `SYMBOL_POOL` 仅作为降级方案（筛选失败或 Redis 无数据时使用）

### 监控文件

| 文件 | 说明 |
|------|------|
| `logs/ai_trader.log` | 主运行日志 |
| `logs/ai_conversations/` | AI 对话详细记录 |
| `logs/position_state.json` | 当前持仓状态（重启自动恢复） |

### 常见问题

**Q: `sign error` 或 `Invalid API key`**  
检查密钥是否复制完整，确认 `OKX_TESTNET` 与密钥类型（模拟/实盘）匹配。

**Q: AI 长时间输出 `wait`**  
正常行为，AI 在等待高概率机会。可降低 `.env` 中 `MIN_RISK_REWARD_RATIO`（如 `1.0`）提高入场频率。

**Q: 重启后止损止盈丢失**  
启用 Redis 后自动恢复；否则从 `logs/position_state.json` 恢复；两者都无则需运行 `python scripts/set_stop_loss.py` 补设。

**Q: 如何切换到实盘**  
修改 `OKX_TESTNET=false`，并填写实盘 `OKX_API_KEY/SECRET_KEY/PASSPHRASE`，重启即可。

## 🤖 AI 模型配置

系统通过 OpenAI 兼容接口支持三种提供商，三选一即可：

| 提供商 | `AI_PROVIDER` | API Key 配置项 | 推荐模型 |
|--------|--------------|---------------|---------|
| OpenAI | `openai` | `OPENAI_API_KEY` | `gpt-4o` |
| 通义千问 | `qwen` | `QWEN_API_KEY` | `qwen2.5-72b-instruct` |
| 豆包 | `doubao` | `DOUBAO_API_KEY` | `doubao-seed-1-8-251228` |

## ⚙️ 核心配置说明

### 交易参数 (.env)

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `STRATEGY_NAME` | 策略名称（对应 strategies/ 目录下的 YAML 文件） | `15m_trend_following` |
| `ENABLE_AUTO_SCREENING` | 是否启用自动筛选标的（每2小时） | `true` |
| `SYMBOL_POOL` | 标的池（逗号分隔），自动筛选关闭时作为主配置 | 空 |
| `INITIAL_CAPITAL` | 初始资金（USDT） | `1000.0` |
| `CYCLE_INTERVAL_SECONDS` | 有持仓时 AI 决策间隔 | `300`（5分钟） |
| `CYCLE_INTERVAL_NO_POSITION` | 无持仓时标的扫描间隔 | `900`（15分钟） |
| `MAX_DAILY_RISK_PCT` | 日亏损上限，超过自动停机 | `8.0` |
| `OKX_TESTNET` | `true`=模拟盘，`false`=实盘 | `false` |

### 策略配置系统

系统支持通过 YAML 文件配置策略，内置 3 种策略：

| 策略名称 | 文件 | 适用场景 | 周期 | 止盈目标 |
|---------|------|---------|------|---------|
| 15分钟短线趋势跟随 | `15m_trend_following.yaml` | 中等波动市场 | 15m | 1.0%-2.0% |
| 5分钟超短线剥头皮 | `5m_scalping.yaml` | 高频快进快出 | 5m | 0.5%-1.2% |
| 1小时波段交易 | `1h_swing.yaml` | 趋势明确市场 | 1h | 2.5%-5.0% |

**切换策略**：在 `.env` 中设置 `STRATEGY_NAME` 即可，无需修改代码。

**可配置参数**（23个）：
- 仓位管理（5个）：最小/最大仓位、强弱趋势仓位等
- 止损参数（3个）：ATR倍数、最大亏损等
- 止盈参数（4个）：最小/常规/强趋势止盈、盈亏比等
- 风控参数（2个）：连续亏损次数、冷却期等
- 持仓时间（3个）：最小/最大持仓时间、止盈浮盈等
- 入场参数（2个）：价格区间宽度等
- 量能参数（2个）：缩量/放量阈值等
- 成本与盈利（3个）：交易成本、盈利要求等

完整说明见 [策略配置系统使用指南](docs/策略配置系统使用指南.md)。

**自定义策略**：复制现有策略文件，修改参数后保存到 `strategies/` 目录即可使用

## 📊 交易决策流程

```
每个决策周期
    ├── 1. 获取最新 K线（5m/15m/1H）
    ├── 2. pandas-ta 计算技术指标（MA/MACD/RSI/BOLL/ATR）
    ├── 3. 识别支撑压力位
    ├── 4. 构建市场数据 → 发送给 AI
    └── 5. 解析 AI 决策
            ├── long  → 风控校验 → 限价买单 → 启动价格监控线程
            ├── close → 撤 TP 挂单 → 市价平仓
            └── wait  → 无操作
```

**AI 输出格式（JSON）：**
```json
{"d":"long","s":80,"e":42800.0,"sl":42100.0,"tp":[44000.0,44900.0],"r":"1h bullish + 5m bounce"}
```

## 🛡️ 风控规则

1. 只做现货、只做多、不杠杆
2. 触发止损立即市价平仓（价格监控线程每秒执行）
3. 盈亏比要求 ≥ `MIN_RISK_REWARD_RATIO`（默认1.5）
4. 日累计亏损 ≥ `MAX_DAILY_RISK_PCT` 时自动停机
5. 连续亏损 ≥ `MAX_CONSECUTIVE_LOSSES` 次后自动降仓

## � 钉钉通知

配置钉钉机器人 Webhook，系统会在以下事件推送消息：
- 开仓（标的、入场价、止损止盈位）
- 止盈成交
- 止损触发
- 风控停机

```env
DINGTALK_ENABLED=true
DINGTALK_WEBHOOK=https://oapi.dingtalk.com/robot/send?access_token=YOUR_TOKEN
DINGTALK_SECRET=YOUR_SECRET    # 加签密钥（可选）
```

## 📋 标的筛选脚本

`scripts/symbol_screener.py` 基于 1H 主周期 + 5m 择时，对所有 OKX 现货标的打分排序：

- 流动性（24h 成交量 ≥ 5亿U、价差 ≤ 0.05%）
- 波动率（ATR ≥ 3%、日振幅 5%-20%）
- 趋势（MA5 > MA10 > MA20，MACD 零轴上方）
- 结构（支撑压力位数量）

```bash
python scripts/symbol_screener.py
```

输出 `scripts/symbol_whitelist.csv`，评分 ≥ 80 为优先标的。详见 [标的筛选脚本使用说明](docs/标的筛选脚本使用说明.md)。

## 🐳 Docker 部署

```bash
cd deployment
docker-compose up -d
docker-compose logs -f app
```

## � 文档

| 文档 | 说明 |
|------|------|
| [模拟盘与实盘配置.md](docs/模拟盘与实盘配置.md) | 两套 API Key 配置和切换方法 |
| [策略配置系统使用指南.md](docs/策略配置系统使用指南.md) | **策略配置系统完整指南**（23个可配置参数、3种内置策略、自定义策略教程） |
| [策略参数配置说明.md](docs/策略参数配置说明.md) | 16个策略参数详解及调整建议 |
| [可配置策略系统使用指南.md](docs/可配置策略系统使用指南.md) | 典型场景调参指南 |
| [TA-Lib指标模块使用说明.md](docs/TA-Lib指标模块使用说明.md) | 技术指标安装和使用说明 |
| [手动设置止损止盈.md](docs/手动设置止损止盈.md) | 手动买入后补设止损止盈 |
| [标的筛选脚本使用说明.md](docs/标的筛选脚本使用说明.md) | 标的筛选脚本配置和使用 |
| [交易记录功能说明.md](docs/交易记录功能说明.md) | Redis 交易历史查询方法 |

## ⚠️ 风险提示

1. 加密货币交易存在高风险，可能损失全部本金
2. AI 决策不保证盈利，请先在模拟盘充分测试
3. 建议从小资金开始，逐步验证
4. 定期检查系统运行日志和持仓状态

## 🔒 安全建议

- ✅ API Key 只开启**交易**权限，**禁止提现**
- ✅ `.env` 文件已在 `.gitignore` 中排除，切勿手动提交
- ✅ 设置 OKX API IP 白名单
- ✅ 定期轮换 API Key

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📄 许可证

MIT License

---

**免责声明**: 本项目仅供学习和研究使用，不构成投资建议。使用本系统进行实盘交易的风险由使用者自行承担。
