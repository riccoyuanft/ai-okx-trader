# AI OKX Trader

基于 AI 大模型的自动化加密货币交易系统，支持 GPT-4o/通义千问/豆包，专注于现货交易。

## 📋 项目概述

这是一个完全自动化的交易系统，由 AI 大模型担任全职交易员角色，负责：
- 🤖 **AI 决策**: 自主判断开仓/平仓/观望
- 📊 **动态仓位**: 0%-100% 灵活调整
- 🛡️ **智能风控**: 止损止盈、风险限额
- 🔄 **24/7 运行**: 每 5 分钟一次决策循环

## ✨ 核心特性

- ✅ 只做现货、只做多、不杠杆
- ✅ 动态仓位管理 (0%-100%)
- ✅ 智能止损止盈 (盈亏比 ≥ 1:1.5)
- ✅ 单日最大风险 3%
- ✅ 连续亏损自动降仓
- ✅ 完整的会话历史记忆
- ✅ 实时监控与告警

## 🏗️ 技术架构

### 技术栈（简化版）
- **语言**: Python 3.11+
- **AI**: OpenAI GPT-4o / 通义千问 / 豆包大模型
- **交易所**: OKX (python-okx SDK)
- **调度**: APScheduler
- **日志**: loguru
- **数据库**: 可选 (PostgreSQL + Redis)

### 系统架构
```
main.py (主循环)
    ├── OKXClient (数据获取 + 交易执行)
    ├── AIAgent (AI 决策)
    ├── RiskManager (风控验证)
    └── Logger (日志记录)
```

**总代码量: ~500行，简单实用！**

## 📁 项目结构（简化版）

```
ai-okx-trader/
├── src/
│   ├── main.py              # 主入口 (~200行)
│   ├── config/
│   │   ├── settings.py      # 配置管理
│   │   └── prompts.py       # AI提示词
│   ├── data/
│   │   ├── models.py        # 数据模型
│   │   └── okx_client.py    # OKX客户端 (~250行)
│   ├── ai/
│   │   └── agent.py         # AI决策器 (~100行)
│   ├── risk/
│   │   └── manager.py       # 风控模块 (~100行)
│   └── monitor/
│       └── logger.py        # 日志配置
├── logs/                    # 日志文件
├── .env                     # 环境变量
├── requirements.txt         # 依赖列表
└── README.md
```

## 🚀 快速开始

### 1. 环境要求

- Python 3.11+
- OKX 账户
- AI API Key (OpenAI / 通义千问 / 豆包，三选一)

**注意**: 数据库和Redis是可选的，不是必须的！

### 1.5 模拟盘 vs 实盘

系统支持两种交易模式:

#### 🧪 模拟盘交易 (推荐新手)
- 使用虚拟资金,不会有真实损失
- 需要在OKX模拟盘创建API Key
- 设置 `OKX_TESTNET=true`

**创建模拟盘API Key**:
1. 登录欧易账户
2. 交易 → 模拟交易
3. 个人中心 → 创建模拟盘APIKey
4. 复制API Key到 `.env` 文件

#### 💰 实盘交易 (真实资金)
- 使用真实资金,盈亏真实
- 需要在OKX实盘创建API Key
- 设置 `OKX_TESTNET=false`
- **强烈建议先在模拟盘测试验证策略**

**创建实盘API Key**:
1. 登录 www.okx.com
2. 个人中心 → API管理
3. 创建API Key (权限: 交易)
4. 复制API Key到 `.env` 文件

### 2. 安装依赖

```bash
# 克隆项目
git clone <repository-url>
cd ai-okx-trader

# 创建虚拟环境
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # Linux/Mac

# 安装依赖
pip install -r requirements.txt
```

### 3. 配置环境变量

```bash
# 复制配置模板
copy .env.example .env  # Windows
# cp .env.example .env  # Linux/Mac

# 编辑 .env 文件，填入必填项:
# - OKX_API_KEY (OKX API密钥)
# - OKX_SECRET_KEY (OKX密钥)
# - OKX_PASSPHRASE (OKX口令)
# - AI_PROVIDER (选择: openai / qwen / doubao)
# - 对应的 AI API Key (根据选择的provider)
```

### 4. 运行系统

```bash
# 直接运行
python -m src.main

# 或者
python src/main.py
```

**就这么简单！不需要数据库，不需要Docker！**

## 🤖 AI 模型配置

系统支持三种 AI 模型，根据需求选择：

### 1. OpenAI GPT-4o (推荐)
```bash
AI_PROVIDER=openai
OPENAI_API_KEY=your_api_key
OPENAI_MODEL=gpt-4o
OPENAI_BASE_URL=https://api.openai.com/v1
```

### 2. 通义千问
```bash
AI_PROVIDER=qwen
QWEN_API_KEY=your_api_key
QWEN_MODEL=qwen2.5-72b-instruct
```

### 3. 豆包大模型
```bash
AI_PROVIDER=doubao
DOUBAO_API_KEY=your_api_key
DOUBAO_MODEL=doubao-seed-1-8-251228
DOUBAO_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
```

**注意**: 只需配置一个 AI 提供商即可，其他可以留空。

## ⚙️ 配置说明

### 核心配置 (.env)

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `SYMBOL` | 交易对 | BTC/USDT |
| `INITIAL_CAPITAL` | 初始资金 | 1000.0 |
| `MAX_DAILY_RISK_PCT` | 单日最大风险 | 3.0 |
| `CYCLE_INTERVAL_SECONDS` | 循环间隔 | 300 (5分钟) |

### AI 提示词

系统提示词位于 `src/config/prompts.py`，定义了 AI 的交易风格和规则。

## 📊 数据流程

### 输入数据格式
```json
{
  "symbol": "BTC/USDT",
  "current_price": 42800.0,
  "latest_klines": {
    "5m": [timestamp, open, high, low, close, volume],
    "15m": [...],
    "1h": [...]
  },
  "position": {
    "has_position": true,
    "entry_price": 42300.0,
    "size_usdt": 500.0,
    "current_pnl_pct": 1.18
  },
  "key_levels": {
    "supports": [42200.0, 41800.0],
    "resistances": [43500.0, 44200.0]
  }
}
```

### AI 输出格式
```json
{
  "d": "long",
  "s": 50,
  "e": 42800.0,
  "sl": 42100.0,
  "tp": [44000.0, 44900.0],
  "r": "1h bullish + 5m bounce"
}
```

## 🛡️ 风控规则

1. **永远不逆势开仓**
2. **触发止损立即平仓**
3. **盈亏比至少 1:1.5**
4. **单日总风险 ≤ 3%**
5. **连续亏损自动降仓**
6. **只在高概率位置开仓**

## 📈 监控指标

### 业务指标
- 总资金余额
- 当日盈亏
- 胜率 / 盈亏比
- 最大回撤

### 技术指标
- API 调用成功率
- 平均响应时间
- 异常次数

## 🧪 测试

```bash
# 运行所有测试
pytest

# 运行特定测试
pytest tests/test_ai_agent.py

# 生成覆盖率报告
pytest --cov=src --cov-report=html
```

## 🐳 Docker 部署

```bash
# 构建并启动所有服务
cd deployment
docker-compose up -d

# 查看日志
docker-compose logs -f app

# 停止服务
docker-compose down
```

## 📝 开发计划

详见 `docs/简化开发方案.md`

### 开发阶段（简化版）
- [x] 阶段一: 基础框架搭建
- [x] 阶段二: OKX客户端封装
- [x] 阶段三: AI决策模块
- [x] 阶段四: 风控模块
- [x] 阶段五: 主控制器
- [ ] 阶段六: 测试与调优
- [ ] 阶段七: 模拟盘验证
- [ ] 阶段八: 实盘部署

**预计总开发时间: 3-4天**

## 💰 成本与收益

### 运行成本
- **每日**: ~$2.16 (144 次 API 调用)
- **每月**: ~$64.8
- **每年**: ~$788

### 预期收益
- **保守**: 年净赚 1000-2700 USDT
- **中性**: 年净赚 2700-5200 USDT
- **乐观**: 年净赚 5200-9200 USDT

## ⚠️ 风险提示

1. 加密货币交易存在高风险
2. AI 决策不保证盈利
3. 建议从小资金开始测试
4. 定期检查系统运行状态
5. 做好资金管理和风险控制

## 🔒 安全建议

- ✅ 使用只读 + 交易权限的 API 密钥（禁止提现）
- ✅ 不要将 `.env` 文件提交到 Git
- ✅ 定期轮换 API 密钥
- ✅ 设置 IP 白名单
- ✅ 启用双因素认证

## 📚 文档

- [初步方案](docs/初步方案.md) - 原始需求和设计
- [开发实现方案](docs/开发实现方案.md) - 完整版方案（较复杂）
- [简化开发方案](docs/简化开发方案.md) - **推荐阅读**，简化实用版

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📄 许可证

MIT License

## 📧 联系方式

如有问题，请提交 Issue 或联系项目维护者。

---

**免责声明**: 本项目仅供学习和研究使用，不构成投资建议。使用本系统进行实盘交易的风险由使用者自行承担。
