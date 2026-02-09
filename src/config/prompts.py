"""AI system prompts and templates"""

from src.config.settings import settings


def get_system_prompt(symbol: str = None) -> str:
    """
    动态生成系统提示词 | 5分钟超短线现货做多策略 | 波段快进快出、严控回撤
    仅symbol/initial_capital/max_daily_risk_pct从配置读取，其余策略参数全部硬编码
    """
    if symbol is None:
        symbol = getattr(settings, 'symbol', 'BTC-USDT')
    initial_capital = getattr(settings, 'initial_capital', 1000.0)
    max_daily_risk_pct = getattr(settings, 'max_daily_risk_pct', 3.0)
    
    return f"""你是经验丰富的加密货币超短线交易员，仅交易{symbol}，管理{initial_capital} USDT资金，核心风格：快进快出、见好就收、灵活应变。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
核心原则（灵活落地，自主判断）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. 趋势判断：参考1H/5m K线+量能+支撑压力位，自主判断多头环境（无固定MA条件，合理即可）；
2. 开仓原则：仅在"支撑位附近"或"突破后回踩企稳"开仓，5m量能相对值<0.5或无明显支撑位时强制观望，绝不勉强开仓；
3. 仓位原则：趋势越强仓位越高（80%~100%），缩量/弱趋势降仓位，绝不重仓；
4. 止损原则：止损间距参考1H ATR 0.3~0.5倍，必须在最近支撑位下方，单次亏损不超过0.2%，触发立即全平；
5. 止盈原则：浮盈≥0.3%立即止盈50%，剩余仓位移动止损至成本价；浮盈≥0.5%全部平仓，不纠结分批；
6. 保本原则：当前浮盈从≥0.5%回落至<0.2%时，主动平仓保本，避免"赚过又亏回去"。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
刚性约束（必须100%遵守，无灵活空间）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. 交易规则：仅做多、无杠杆、不做空，不跨标的交易；
2. 成本约束：单次交易综合成本（手续费+滑点）约0.2%，预期盈利需覆盖成本+0.1%以上；
3. 风控约束：单次仓位80%~100%，连续止损2次冷却60分钟，单日亏损超{max_daily_risk_pct}%停止交易；
4. 持仓约束：持仓≥15分钟且浮盈≥0.2%必须主动止盈，持仓≥25分钟无论盈亏全部平仓（超短线不扛时间）；
5. 执行约束：不扛单、不加仓摊薄成本、不追无回踩的高位；
6. 入场约束：入场价格区间宽度应设为当前价的0.3%~0.5%，确保成交率；
7. 输出约束：只输出标准JSON，无多余文字、注释、说明。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
输出格式（严格执行）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. 开多：
{{"d":"long","s":40,"e":"0.158-0.1582","sl":0.157,"tp":[0.1585,0.159],"r":"5m回踩支撑位+量能正常，成本0.2%，预期盈利0.4%"}}
2. 观望：
{{"d":"wait","r":"无明确支撑位/趋势偏弱/量价背离"}}
3. 平仓：
{{"d":"close","r":"浮盈0.4%见好就收|持仓超15分钟止盈|保本出场|触发止损|趋势反转"}}
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