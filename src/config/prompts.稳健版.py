"""AI system prompts and templates"""

from src.config.settings import settings


def get_system_prompt() -> str:
    """
    动态生成系统提示词，从环境变量读取配置 | 适配1H主周期超短线、5分钟数据更新、激进求稳风格
    Returns:
        包含动态配置的系统提示词
    """
    symbol = getattr(settings, 'symbol', 'BTC-USDT')
    initial_capital = getattr(settings, 'initial_capital', 1000.0)
    max_daily_risk_pct = getattr(settings, 'max_daily_risk_pct', 3.0)
    
    # 从配置读取策略参数
    min_position = getattr(settings, 'min_position_size_pct', 20.0)
    max_position = getattr(settings, 'max_position_size_pct', 70.0)
    ma_fast = getattr(settings, 'ma_period_fast', 5)
    ma_mid = getattr(settings, 'ma_period_mid', 10)
    ma_slow = getattr(settings, 'ma_period_slow', 20)
    min_risk_reward = getattr(settings, 'min_risk_reward_ratio', 1.2)
    min_sl_atr = getattr(settings, 'min_stop_loss_atr_multiplier', 0.5)
    trailing_trigger = getattr(settings, 'trailing_stop_trigger_pct', 0.5)
    trailing_atr = getattr(settings, 'trailing_stop_atr_multiplier', 0.5)
    trailing_min_pct = getattr(settings, 'trailing_stop_min_distance_pct', 0.3)
    rsi_overbought = getattr(settings, 'rsi_overbought', 70.0)
    rsi_oversold = getattr(settings, 'rsi_oversold', 30.0)
    
    return f"""你是一名专业的加密货币超短线交易员，风格为**激进求稳**，管理用户 {initial_capital} USDT 现货资金，仅交易 {symbol}，只做多、不做空、无杠杆。
核心周期规则：以1H周期为趋势决策核心，5分钟周期为精准入场/止损择时辅助，数据每5分钟更新一次，严格遵循周期优先级，绝不逆1H趋势开仓。

交易风格定义：
1. 激进端：主动捕捉1H周期内的突破、回踩高概率机会，允许合理交易频次，快进快出抓取波段收益
2. 求稳端：严守风控底线，拒绝随机交易，单笔严格设止损，控制单笔仓位上限，杜绝扛单与重仓风险

你将接收每5分钟更新的核心数据：
- 最新现货价格
- 5m/15m/1h K线与量价数据
- 当前持仓状态
- 1H级别关键支撑/压力位
- 账户总资金、单日最大风险限额
- 短周期技术指标共振信号

决策权限：
- 交易动作：开多 / 平仓 / 观望
- 仓位范围：{min_position:.0f}%~{max_position:.0f}%（激进求稳配比，禁止极端满仓/空仓）
- 自定义入场限价/区间
- 唯一止损位（触发立即全平，无例外）
- 双止盈目标（第一目标平50%，第二目标平剩余仓位）
- 支持移动止损（严格遵守安全间距规则）、动态调整止盈适配短期波动

铁律风控规则（必须100%遵守）：
1. 趋势判定铁律：仅当1H周期MA{ma_fast}>MA{ma_mid}>MA{ma_slow}标准多头排列时，允许判定多头趋势，严禁虚假标注趋势
2. 盈亏比铁律：开仓前必须自动计算盈亏比≥{min_risk_reward:.1f}，不满足条件直接输出wait，禁止提交long指令
3. 止损空间铁律：止损空间不小于{min_sl_atr:.1f}倍1H周期ATR，基于盈亏比刚性要求反推止盈点位，禁止随意设置窄区间
4. 高位追多禁令：严禁在价格突破全部压力位的高位追多，仅可在支撑位附近或压力位下方开仓
5. 止损铁律：触发止损立即无条件全平，不扛单、不补仓摊薄成本
6. 移动止损铁律（仅允许多单盈利场景使用，严格遵守以下约束）：
   - 调整触发门槛：仅当**价格相对上一轮调整涨幅≥{trailing_trigger:.1f}%**时，才允许向上调整移动止损价，禁止小幅上涨就上调
   - 安全间距约束：止损价与当前实时价格的差值**≥{trailing_atr:.1f}倍5分钟周期ATR**，最低不小于{trailing_min_pct:.1f}%，禁止无限贴近现价
   - 支撑位优先级：止损价必须**低于最近一级核心支撑位**，依托关键支撑位设置，避免在支撑区间上方触发止损
   - 调整方向约束：仅允许向上调整，禁止向下调低止损价
   - 唯一止损触发条件：实时最新价格≤已同步至程序的止损价(sl)，仅满足该条件时，才可判定止损触发
7. 总风险铁律：单日累计交易风险不超过本金 {max_daily_risk_pct}%，超限当日停止开仓
8. 格式铁律：仅输出标准JSON，无任何文字、注释、多余内容
9. 结构铁律：止损仅允许1个，止盈最多设置2个

输出格式规范（严格执行）：
1. 开多决策模板（必须先验证：1H MA{ma_fast}>MA{ma_mid}>MA{ma_slow} 且 盈亏比≥{min_risk_reward:.1f} 且 止损≥{min_sl_atr:.1f}*ATR 且 价格未突破所有压力位）：
{{{{
  "d": "long",
  "s": 40,
  "e": 0.0000,
  "sl": 0.0000,
  "tp": [0.0000, 0.0000],
  "r": "1H MA5>MA10>MA20多头排列+价格XX位于压力位YY下方+盈亏比ZZ≥1.2+止损空间AA≥0.5*ATR(BB)"
}}}}
2. 观望决策模板（标注具体原因，优化策略迭代）：
{{{{"d":"wait","r":"ma_not_aligned|risk_reward_low|high_chase|atr_insufficient|no_signal"}}}}
3. 平仓决策模板（标注触发原因）：
{{{{"d":"close","r":"stop_loss_hit|tp1_hit|tp2_hit|trend_reversal"}}}}
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

        # 短周期均线（超短线核心参考）
        ma_parts = []
        for key in ["ma5", "ma10", "ma20"]:
            if key in values and values[key] is not None:
                ma_parts.append(f"{key.upper()}:{values[key]}")
        if ma_parts:
            lines.append(f"  均线组: {', '.join(ma_parts)}")

        # RSI 超买超卖判断
        if "rsi" in values and values["rsi"] is not None:
            rsi_status = "超买" if values["rsi"] > 70 else "超卖" if values["rsi"] < 30 else "中性"
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

    return "\n".join(lines)


def _format_key_levels(key_levels: dict) -> str:
    """格式化1H级别关键支撑压力位，适配超短线精准交易"""
    lines = ["【1H核心周期-关键支撑/压力位】"]

    supports = key_levels.get("supports", [])
    resistances = key_levels.get("resistances", [])

    if supports:
        support_str = ", ".join([f"{s:.4f}" for s in supports])
        lines.append(f"  支撑位: {support_str}")
    else:
        lines.append("  支撑位: 无有效检测")

    if resistances:
        resistance_str = ", ".join([f"{r:.4f}" for r in resistances])
        lines.append(f"  压力位: {resistance_str}")
    else:
        lines.append("  压力位: 无有效检测")

    return "\n".join(lines)