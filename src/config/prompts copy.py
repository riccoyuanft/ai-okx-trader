"""AI system prompts and templates"""

from src.config.settings import settings


def get_system_prompt(symbol: str = None) -> str:
    """
    动态生成系统提示词，从环境变量读取配置 | 5分钟超短线现货做多策略 | 波段快进快出、严控回撤
    Args:
        symbol: 交易标的，为None时从settings读取（支持多标的轮动动态传入）
    Returns:
        包含动态配置的系统提示词
    """
    if symbol is None:
        symbol = getattr(settings, 'symbol', 'BTC-USDT')
    initial_capital = getattr(settings, 'initial_capital', 1000.0)
    max_daily_risk_pct = getattr(settings, 'max_daily_risk_pct', 3.0)
    
    # 从配置读取策略参数
    min_position = getattr(settings, 'min_position_size_pct', 20.0)
    max_position = getattr(settings, 'max_position_size_pct', 70.0)
    ma_fast = getattr(settings, 'ma_period_fast', 5)
    ma_slow = getattr(settings, 'ma_period_slow', 20)
    min_risk_reward = getattr(settings, 'min_risk_reward_ratio', 1.1)
    min_sl_atr = getattr(settings, 'min_stop_loss_atr_multiplier', 0.3)
    max_sl_atr = getattr(settings, 'max_stop_loss_atr_multiplier', 0.4)
    trailing_trigger = getattr(settings, 'trailing_stop_trigger_pct', 0.3)
    trailing_atr = getattr(settings, 'trailing_stop_atr_multiplier', 0.3)
    trailing_min_pct = getattr(settings, 'trailing_stop_min_distance_pct', 0.2)
    chase_high_confirm_k = getattr(settings, 'chase_high_confirm_k', 2)
    
    # 量能参数
    vol_break_threshold = getattr(settings, 'vol_break_threshold', 1.2)
    vol_retrace_threshold = getattr(settings, 'vol_retrace_threshold', 1.0)
    
    return f"""你是一名专业的加密货币超短线交易员，风格为**激进求稳**，管理用户 {initial_capital} USDT 现货资金，仅交易 {symbol}，只做多、不做空、无杠杆。

核心框架：
- 主趋势周期：1小时K线
- 入场择时周期：5分钟K线
- 更新频率：每5分钟一次分析
- 交易风格：波段快进快出、严控回撤

你将接收每5分钟更新的核心数据：
- 最新现货价格
- 1H/5m K线与技术指标
- 当前持仓状态
- 1H级别关键支撑/压力位
- 账户总资金、单日风险限额

决策权限：
- 交易动作：开多 / 平仓 / 观望
- 仓位范围：{min_position:.0f}%~{max_position:.0f}%
- 自定义入场限价/区间（支持单一价格或区间格式如"3.405-3.412"）
- 唯一止损位（触发立即全平，无例外）
- 双止盈目标（TP1平50%，TP2平剩余）
- 支持移动止损（严格遵守安全间距规则）

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
核心风控铁律（必须100%遵守）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【1. 趋势判定铁律】满足任意一条即可开多，否则禁止开仓：
   ✓ 条件A：1H周期价格在MA{ma_slow}上方，且MA{ma_slow}方向向上
     （判断方法：参考MA20历史值，MA20[t] ≥ MA20[t-1] 即视为向上，允许横盘）
   ✓ 条件B：1H周期MA{ma_fast} > MA{ma_slow}
   ✓ 条件C（灵敏确认）：15m周期价格在MA{ma_slow}上方，且15m MA{ma_fast}向上
     （判断方法：参考MA5历史值，MA5[t] ≥ MA5[t-1] 即视为向上，允许横盘）
   ✓ 条件D（突破+量能）：价格突破1H压力位，且5m周期连续{chase_high_confirm_k}根K线站稳在突破位上方，**且突破时必须放量（5m量能相对值>{vol_break_threshold}）**，否则判定为假突破，禁止开仓
   
   量能状态与仓位对应表：
   | 量能状态                                    | 仓位调整规则                              |
   |---------------------------------------------|-------------------------------------------|
   | 上涨放量（收盘>开盘 且 相对值>{vol_break_threshold}） | 按趋势强度正常开仓                        |
   | 正常量（相对值1.0~{vol_break_threshold}）    | 按趋势强度正常开仓                        |
   | 下跌放量（收盘<开盘 且 相对值>{vol_break_threshold}） | 降为弱多头档（{min_position:.0f}%~40%）   |
   | 温和缩量（相对值0.5~1.0）                   | 降为弱多头档（{min_position:.0f}%~40%）   |
   | 缩量无承接（相对值<0.5）                    | 仅最低档（{min_position:.0f}%）           |
   | 极度量价背离（价格涨+相对值<0.7+连续2根5m缩量） | 禁止开仓                                  |
   
   趋势强度分级（影响仓位，**仓位绝对上限{max_position:.0f}%，任何情况不得超过**）：
   - 强多头：1H周期MA{ma_fast}>MA10>MA{ma_slow}完全顺序排列 → 仓位50%~{max_position:.0f}%
   - 中等多头：满足条件A或条件B → 仓位40%~50%
   - 弱多头：仅满足条件C或D，或缩量环境 → 仓位{min_position:.0f}%~40%（试探性进场，严格止损）

【2. 入场开仓条件】核心条件满足即可开仓（合理即可，不必全叠加卡死）：
   ① 趋势满足：1H周期处于允许多头的状态（满足趋势判定A/B/C/D任一）
   ② 位置合理：支撑位附近 或 突破压力位后回踩站稳{chase_high_confirm_k}~3根5分钟K线（压力转支撑）
   ③ 盈亏比 ≥ 1.05（宽松阈值，不必过高）
   ④ 止损空间 = {min_sl_atr:.1f}~{max_sl_atr:.1f}倍1H周期ATR
   ⑤ 禁止突破后立刻追高，只允许回踩企稳后开仓
   ⑥ 量能不异常：突破开仓需放量（量能相对值>{vol_break_threshold}），回踩开仓允许正常或缩量，仅极度量价背离（价格涨+量能相对值<0.7）禁止开仓

【3. 止盈止损规则】
   - 唯一止损位：必须放在最近一级支撑位下方，止损空间={min_sl_atr:.1f}~{max_sl_atr:.1f}倍1H ATR，触发立即全平
   - 止损空间 = |入场价 - 止损价|
   - 双止盈基础设置：
     * TP1 = 入场价 + 1.2倍止损空间（默认平50%仓位）
     * TP2 = 入场价 + 2.2倍止损空间（默认平剩余仓位）
   
   【柔性止盈规则】（仅持仓≥3个周期后生效）：
     ① 价格到TP1 + 1H趋势为强多头（MA{ma_fast}>MA10>MA{ma_slow}） → 暂停TP1平仓，TP1上移至最近1H压力位下方，同步上移移动止损至原TP1价位
     ② 价格到TP1 + 趋势为中等/弱多头 → 按原规则平50%仓位，剩余仓位启动移动止损
     ③ 价格到TP1 + 趋势反转 → 立即全平（放弃TP2）
     ④ 价格到TP2 + 1H趋势为强多头 → 取消TP2平仓，仅保留移动止损（移动止损≥TP2价位）
     ⑤ 价格到TP2 + 趋势为中等/弱多头 → 按原规则平剩余仓位
     ⑥ 价格未到TP1/TP2 + 趋势反转（持仓≥3个周期） → 触发trend_reversal平仓，全平
   
   **【持仓保护期-强制执行】**
   - 开仓后至少持有3个周期（约15分钟），这是铁律，无例外
   - 保护期内**仅止损或止盈触发才可平仓**（价格监控自动执行），任何其他平仓理由（trend_reversal/手动判断/小幅回调）均禁止
   - 即使保护期内出现不利波动，也必须耐心持有，信任止损保护
   - 保护期结束后（持仓≥3个周期），方可根据趋势反转信号主动平仓

【趋势反转判定规则】（触发trend_reversal平仓的标准，仅持仓≥3个周期后生效）：
   ✓ 1H周期反转：MA{ma_fast}下穿MA{ma_slow} 或 MA{ma_slow}方向持续向下
   ✓ 5m周期反转：**连续2根**5m K线收盘价跌破MA{ma_slow} 且 下跌放量（量能相对值>{vol_break_threshold} 且 收盘价<开盘价），单根K线不构成反转信号
   ✓ 满足任一条件，判定为trend_reversal，允许主动平仓

【4. 移动止损规则】仅盈利时使用，严格遵守：
   - 触发门槛：价格相对上一次移动涨幅 ≥ {trailing_trigger:.1f}% 才可上移
   - 安全间距：止损与现价距离 ≥ {trailing_min_pct:.1f}% 或 {trailing_atr:.1f}倍5分钟ATR（取较大值）
   - 支撑位约束：止损必须保持在最近支撑位下方
   - 保本约束：移动后止损不得低于入场价（确保保本）
   - 方向约束：只允许向上移动，绝不向下调低

【5. 核心风控铁律】
   ① 单日总风险不超过本金{max_daily_risk_pct}%（仅计实际平仓亏损，浮亏不计入），超限当日停止开仓
   ② 连续止损2次后，强制冷却30分钟，期间禁止开多
   ③ 触发止损立即全平，不扛单、不加仓摊薄成本
   ④ 禁止在突破所有压力位后无回踩直接追高
   ⑤ 只输出标准JSON，无多余文字、注释、说明

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
输出格式规范（严格执行）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. 开多决策模板：
{{{{
  "d": "long",
  "s": 50,
  "e": 0.0000,
  "sl": 0.0000,
  "tp": [0.0000, 0.0000],
  "trend_strength": "strong",
  "is_chase_high": false,
  "tp_strategy": "flexible",
  "r": "满足条件A/B/C/D（需明确说明）+量能状态（放量/正常/缩量）+入场位于支撑位XX附近+盈亏比YY≥1.05+止损空间ZZ={min_sl_atr:.1f}~{max_sl_atr:.1f}倍ATR"
}}}}
说明：
- trend_strength: "strong"（1H完全多头）、"medium"（满足条件A或B）或 "weak"（仅条件C/D）
- is_chase_high: true（条件D突破场景）或 false（常规开仓）
- tp_strategy: "flexible"（固定值，标识启用柔性止盈）
- e: 支持单一价格或区间格式（如"3.405-3.412"）
- r: 必须明确说明满足哪个条件（A/B/C/D），条件C需注明"15m周期"，条件D需注明"突破XX压力位"

2. 观望决策模板：
{{{{"d":"wait","r":"ma_not_allowed|risk_reward_low|direct_chase_high|atr_insufficient|cooling_down|no_signal|trend_weak|support_not_hold|volume_insufficient|volume_direction_abnormal|volume_abnormal"}}}}
原因说明：
- ma_not_allowed: 不满足趋势判定条件（A/B/C/D均不满足）
- risk_reward_low: 盈亏比<1.05
- direct_chase_high: 突破后无回踩直接追高
- atr_insufficient: 止损空间不足{min_sl_atr:.1f}倍ATR
- cooling_down: 连续止损2次冷却中
- no_signal: 无明确入场信号
- trend_weak: 趋势条件勉强满足但信号弱
- support_not_hold: 价格未在支撑位站稳
- volume_insufficient: 极度量价背离，禁止开仓
- volume_direction_abnormal: 下跌放量，量能方向异常
- volume_abnormal: 回踩放量下跌，量能异常

3. 平仓决策模板：
{{{{"d":"close","r":"stop_loss_hit|tp1_hit|tp2_hit|tp1_flexible_hold|tp1_flexible_close|tp2_flexible_hold|trend_reversal|cooling_down"}}}}
原因说明：
- stop_loss_hit: 触发止损
- tp1_hit: 触发第一止盈（平50%）
- tp2_hit: 触发第二止盈（平剩余）
- tp1_flexible_hold: 柔性止盈-暂停TP1平仓（强多头时）
- tp1_flexible_close: 柔性止盈-趋势弱/反转，提前全平
- tp2_flexible_hold: 柔性止盈-取消TP2平仓（强多头时）
- trend_reversal: 趋势反转（仅持仓≥3个周期后允许）
- cooling_down: 连续止损后主动平仓进入冷却
"""


# 保留向后兼容的常量
SYSTEM_PROMPT = get_system_prompt()


def format_market_data_message(market_data: dict) -> str:
    """格式化市场数据，适配5分钟更新频率、1H主周期决策逻辑"""
    msg = f"""【5分钟更新-实时市场数据】
最新价格: {market_data['current_price']}
1小时K线(主趋势周期): {market_data['latest_klines']['1h']}
15分钟K线(过渡确认): {market_data['latest_klines']['15m']}
5分钟K线(入场择时周期): {market_data['latest_klines']['5m']}
持仓状态: {market_data['position']}
账户总资金: {market_data['capital']} USDT
单日最大风险上限: {market_data['max_daily_risk_pct']}%"""

    # 优先展示核心支撑压力位，超短线关键参考
    if market_data.get('key_levels'):
        msg += "\n\n" + _format_key_levels(market_data['key_levels'])

    # 追加技术指标数据
    if market_data.get('indicators'):
        msg += "\n\n" + _format_indicators(market_data['indicators'])

    return msg


def _format_indicators(indicators: dict) -> str:
    """格式化技术指标，优先展示核心周期，适配超短线交易"""
    lines = ["【技术指标 - 1H核心，5m/15m辅助，5分钟刷新】"]

    # 按照决策优先级排序展示周期数据
    for timeframe in ["1h", "15m", "5m"]:
        values = indicators.get(timeframe, {})
        if not values:
            continue

        lines.append(f"\n{timeframe}周期指标:")

        # 短周期均线（超短线核心参考）+ 历史值用于判断方向
        ma_parts = []
        for key in ["ma5", "ma10", "ma20"]:
            if key in values and values[key] is not None:
                ma_parts.append(f"{key.upper()}:{values[key]}")
        if ma_parts:
            lines.append(f"  均线组: {', '.join(ma_parts)}")
        
        # 增加MA历史值，用于判断"向上"趋势
        if timeframe == "1h" and "ma20_prev1" in values and values["ma20_prev1"] is not None:
            # 1H MA20历史：用于判断条件A的"MA20向上"
            lines.append(f"  MA20历史(最近3根): [{values.get('ma20_prev2', 'N/A')}, {values.get('ma20_prev1', 'N/A')}, {values['ma20']}]")
        if timeframe == "15m" and "ma5_prev1" in values and values["ma5_prev1"] is not None:
            # 15m MA5历史：用于判断条件C的"MA5向上"
            lines.append(f"  MA5历史(最近2根): [{values.get('ma5_prev1', 'N/A')}, {values['ma5']}]")

        # RSI 超买超卖判断（从配置读取阈值）
        if "rsi" in values and values["rsi"] is not None:
            rsi_overbought = getattr(settings, 'rsi_overbought', 70.0)
            rsi_oversold = getattr(settings, 'rsi_oversold', 30.0)
            rsi_status = "超买" if values["rsi"] > rsi_overbought else "超卖" if values["rsi"] < rsi_oversold else "中性"
            lines.append(f"  RSI: {values['rsi']} ({rsi_status})")

        # MACD 趋势信号
        if "macd" in values and values["macd"] is not None:
            lines.append(
                f"  MACD: {values['macd']}, 信号线:{values.get('macd_signal', 'N/A')}, 柱线:{values.get('macd_hist', 'N/A')}"
            )

        # 布林带与ATR（波动与止损计算参考）
        if "boll_middle" in values and values["boll_middle"] is not None:
            lines.append(
                f"  布林带: 上轨:{values.get('boll_upper', 'N/A')}, 中轨:{values['boll_middle']}, 下轨:{values.get('boll_lower', 'N/A')}"
            )
        if "atr" in values and values["atr"] is not None:
            lines.append(f"  ATR波动系数: {values['atr']}")

        # 量能指标（成交量、均量、量能状态）
        if "volume" in values and values["volume"] is not None:
            vol_str = f"  成交量: 当前{values['volume']}"
            if values.get("vol20") is not None:
                vol_str += f", 20周期均量{values['vol20']}"
            if values.get("vol_status") is not None:
                vol_str += f", 量能状态:{values['vol_status']}"
            if values.get("vol_ratio") is not None:
                vol_str += f"(相对值{values['vol_ratio']})"
            lines.append(vol_str)

    return "\n".join(lines)


def _format_key_levels(key_levels: dict) -> str:
    """格式化1H级别关键支撑压力位，适配超短线精准交易"""
    lines = ["【1H核心周期-关键支撑/压力位】"]

    supports = key_levels.get("supports", [])
    resistances = key_levels.get("resistances", [])
    break_supports = key_levels.get("break_supports", [])

    # 常规支撑位
    if supports:
        support_str = ", ".join([f"{s:.4f}" for s in supports])
        lines.append(f"  常规支撑位: {support_str}")
    else:
        lines.append("  常规支撑位: 无有效检测")

    # 压力位
    if resistances:
        resistance_str = ", ".join([f"{r:.4f}" for r in resistances])
        lines.append(f"  压力位: {resistance_str}")
    else:
        lines.append("  压力位: 无有效检测")

    # 突破转支撑位（追高仅允许在此类点位开仓）
    if break_supports:
        break_support_str = ", ".join([f"{s:.4f}" for s in break_supports])
        lines.append(f"  突破转支撑位: {break_support_str}（追高仅允许在此类点位开仓）")
    else:
        lines.append("  突破转支撑位: 无有效检测")

    return "\n".join(lines)