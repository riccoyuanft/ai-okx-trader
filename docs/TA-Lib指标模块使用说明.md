# 技术指标模块使用说明

本项目使用 **pandas-ta** 计算所有技术指标（不依赖 TA-Lib C 库）。

## 📦 安装

所有依赖已在 `requirements.txt` 中声明，直接安装即可：

```bash
pip install -r requirements.txt
```

验证安装：

```bash
python -c "import pandas_ta; print('pandas-ta OK:', pandas_ta.version)"
```

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
# 示例：添加 Stochastic KDJ 指标（使用 pandas_ta）
if len(df) >= 9:
    stoch = ta.stoch(df['high'], df['low'], df['close'], k=9, d=3)
    if stoch is not None and not stoch.empty:
        indicators["kdj_k"] = self._safe_value(stoch.iloc[-1, 0])
        indicators["kdj_d"] = self._safe_value(stoch.iloc[-1, 1])
```

然后在 `src/config/prompts.py` 的 `_format_indicators()` 中添加格式化逻辑。

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

如果 pandas-ta 未安装或计算失败：

```
2026-02-06 11:23:45 | WARNING | src.indicators.ta_calculator - pandas-ta未安装，技术指标计算功能将不可用
```

系统会继续运行，但不会传递指标数据给 AI。建议安装 pandas-ta 以获得完整功能。

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

### 问题1：ImportError: No module named 'pandas_ta'

**解决方案**：运行 `pip install pandas-ta`

### 问题2：指标值全部为 None/N/A

**原因**：K线数据不足

**解决方案**：确保获取了足够的历史K线数据

### 问题3：计算速度慢

**原因**：K线数据量过大

**解决方案**：减少K线数量或优化计算逻辑

---

