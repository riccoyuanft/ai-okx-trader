"""AI system prompts and templates"""

from src.config.settings import settings
from src.config.strategy_loader import get_strategy_loader


def get_system_prompt(symbol: str = None) -> str:
    """
    动态生成系统提示词，从策略配置文件加载
    策略通过.env中的STRATEGY_NAME配置切换
    
    Args:
        symbol: 交易标的，如果为None则从配置读取
    
    Returns:
        格式化的系统提示词
    """
    # 获取策略加载器
    strategy_loader = get_strategy_loader()
    
    # 准备运行时变量
    if symbol is None:
        symbol = getattr(settings, 'symbol', 'BTC-USDT')
    initial_capital = getattr(settings, 'initial_capital', 1000.0)
    max_daily_risk_pct = getattr(settings, 'max_daily_risk_pct', 8.0)
    
    # 使用策略加载器格式化提示词
    return strategy_loader.format_prompt(
        symbol=symbol,
        initial_capital=initial_capital,
        max_daily_risk_pct=max_daily_risk_pct
    )


# 保留向后兼容的常量
SYSTEM_PROMPT = get_system_prompt()


def format_market_data_message(market_data: dict) -> str:
    """格式化市场数据，适配15分钟短线决策逻辑"""
    msg = f"""【实时市场数据】
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