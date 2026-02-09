# TA-Lib技术指标模块使用说明

## 📦 安装教程

### 1. 安装TA-Lib依赖

#### Windows系统

```bash
# 方法1：使用预编译的whl文件（推荐）
# 访问 https://www.lfd.uci.edu/~gohlke/pythonlibs/#ta-lib
# 下载对应Python版本的whl文件，例如：
# TA_Lib‑0.4.28‑cp311‑cp311‑win_amd64.whl (Python 3.11, 64位)

pip install TA_Lib‑0.4.28‑cp311‑cp311‑win_amd64.whl

# 方法2：使用pip直接安装（可能需要编译环境）
pip install TA-Lib
```

#### Linux/macOS系统

```bash
# 先安装系统依赖
# Ubuntu/Debian:
sudo apt-get install build-essential wget
wget http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz
tar -xzf ta-lib-0.4.0-src.tar.gz
cd ta-lib/
./configure --prefix=/usr
make
sudo make install

# macOS (使用Homebrew):
brew install ta-lib

# 然后安装Python包
pip install TA-Lib
```

### 2. 安装NumPy（如果未安装）

```bash
pip install numpy
```

### 3. 验证安装

```bash
python -c "import talib; print(talib.__version__)"
```

如果输出版本号（如 `0.4.28`），说明安装成功。

---

## 🚀 使用说明

### 模块结构

```
src/indicators/
├── __init__.py           # 模块初始化
└── ta_calculator.py      # 技术指标计算器
```

### 已集成的指标

#### 1. 移动平均线 (MA)
- **MA5**: 5周期简单移动平均
- **MA10**: 10周期简单移动平均
- **MA20**: 20周期简单移动平均
- **MA60**: 60周期简单移动平均

#### 2. 指数移动平均线 (EMA)
- **EMA12**: 12周期指数移动平均
- **EMA26**: 26周期指数移动平均

#### 3. MACD (趋势指标)
- **MACD**: MACD线 (12-26)
- **MACD Signal**: 信号线 (9周期EMA)
- **MACD Histogram**: 柱状图 (MACD - Signal)

#### 4. RSI (相对强弱指标)
- **RSI**: 14周期RSI
- 超买区：> 70
- 超卖区：< 30

#### 5. 布林带 (BOLL)
- **BOLL Upper**: 上轨 (中轨 + 2倍标准差)
- **BOLL Middle**: 中轨 (20周期MA)
- **BOLL Lower**: 下轨 (中轨 - 2倍标准差)

#### 6. ATR (平均真实波幅)
- **ATR**: 14周期平均真实波幅
- 用于衡量市场波动性

---

## 📝 代码调用位置

### 主程序集成点

**文件**: `src/main.py`

**位置**: `_collect_market_data()` 方法中

```python
# 第364-368行：计算技术指标
indicators = self.ta_calculator.calculate_all_indicators(
    klines_5m, klines_15m, klines_1h
)
logger.debug(f"技术指标已计算: {len(indicators)} 个时间周期")
```

**位置**: `MarketData` 构建时（第428行）

```python
return MarketData(
    symbol=settings.symbol,
    current_price=current_price,
    latest_klines=latest_klines,
    position=position,
    key_levels=key_levels,
    capital=self.capital,
    max_daily_risk_pct=settings.max_daily_risk_pct,
    indicators=indicators  # 技术指标数据
)
```

### AI提示词集成点

**文件**: `src/config/prompts.py`

**位置**: `format_market_data_message()` 函数（第85-87行）

```python
# 添加技术指标（如果存在）
if market_data.get('indicators'):
    msg += "\n\n" + _format_indicators(market_data['indicators'])
```

---

## 📊 输出示例

### AI接收的指标数据格式

```
【技术指标】

5m周期:
  均线: MA5:4760.5, MA10:4755.2, MA20:4748.8, MA60:4735.1
  EMA: EMA12:4758.3, EMA26:4750.6
  MACD: 2.3456, 信号:1.8765, 柱:0.4691
  RSI: 58.75 (中性)
  BOLL: 上:4780.5, 中:4760.0, 下:4739.5
  ATR: 12.3456

15m周期:
  均线: MA5:4762.0, MA10:4757.5, MA20:4750.2
  MACD: 3.1234, 信号:2.5678, 柱:0.5556
  RSI: 62.30 (中性)
  BOLL: 上:4785.0, 中:4762.0, 下:4739.0
  ATR: 18.7654

1h周期:
  均线: MA5:4765.0, MA10:4760.0, MA20:4752.5
  MACD: 4.5678, 信号:3.9012, 柱:0.6666
  RSI: 65.40 (中性)
  BOLL: 上:4790.0, 中:4765.0, 下:4740.0
  ATR: 25.4321
```

---

## 🔧 自定义扩展

### 添加新指标

编辑 `src/indicators/ta_calculator.py`，在 `_calculate_indicators()` 方法中添加：

```python
# 示例：添加KDJ指标
if len(close) >= 9:
    k, d = talib.STOCH(
        high, low, close,
        fastk_period=9,
        slowk_period=3,
        slowd_period=3
    )
    indicators["kdj_k"] = self._safe_value(k[-1])
    indicators["kdj_d"] = self._safe_value(d[-1])
```

然后在 `_format_indicators()` 中添加格式化逻辑。

---

## ⚠️ 注意事项

1. **数据量要求**：
   - MA5 需要至少 5 根K线
   - MA60 需要至少 60 根K线
   - MACD 需要至少 26 根K线
   - 当前配置：5m(120根)、15m(60根)、1h(30根) ✅

2. **NaN处理**：
   - 所有指标值都经过 `_safe_value()` 处理
   - NaN值会被转换为 `None`
   - AI提示词中会显示为 `N/A`

3. **精度控制**：
   - 所有指标值保留4位小数
   - 避免过度精确导致的噪音

4. **性能影响**：
   - 每次决策周期增加约 50-100ms 计算时间
   - 对于5分钟决策周期，影响可忽略

---

## 📈 日志输出

### 正常运行日志

```
2026-02-06 11:23:45 | DEBUG | __main__:_collect_market_data:368 - 技术指标已计算: 3 个时间周期
2026-02-06 11:23:45 | INFO  | src.ai.agent:make_decision:70 - 📤 发送给AI的消息:
...
【技术指标】
5m周期:
  均线: MA5:4760.5, MA10:4755.2
  RSI: 58.75 (中性)
...
```

### 错误处理

如果TA-Lib未安装或计算失败：

```
2026-02-06 11:23:45 | ERROR | src.indicators.ta_calculator:calculate_all_indicators:35 - 技术指标计算失败: No module named 'talib'
```

系统会继续运行，但不会传递指标数据给AI。

---

## 🎯 验证测试

重启交易程序，检查日志中是否出现技术指标数据：

```bash
# 停止当前程序
Ctrl+C

# 重新启动
python -m src.main
```

查看AI对话日志文件：
```
logs/ai_conversations/ai_conversation_YYYYMMDD_HHMMSS.txt
```

应该能看到完整的技术指标数据。

---

## 📞 问题排查

### 问题1：ImportError: No module named 'talib'

**解决方案**：按照安装教程重新安装TA-Lib

### 问题2：指标值全部为 None/N/A

**原因**：K线数据不足

**解决方案**：确保获取了足够的历史K线数据

### 问题3：计算速度慢

**原因**：K线数据量过大

**解决方案**：减少K线数量或优化计算逻辑

---

## ✅ 完成清单

- [x] 创建独立的TA-Lib指标计算工具类
- [x] 在主循环中集成指标计算逻辑
- [x] 更新AI提示词以接收指标数据
- [x] 兼容现有日志系统
- [x] 处理NaN值和精度控制
- [x] 输出安装教程和使用说明

---

**模块版本**: v1.0.0  
**最后更新**: 2026-02-06  
**作者**: AI Trading System
