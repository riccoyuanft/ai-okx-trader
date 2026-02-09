"""
检查UXLINK是否满足筛选条件
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.data.okx_client import OKXClient
from src.indicators.ta_calculator import TACalculator
from loguru import logger

def check_uxlink():
    symbol = "UXLINK-USDT"
    client = OKXClient()
    calculator = TACalculator()
    
    logger.info(f"正在检查 {symbol} 的筛选条件...")
    
    # 1. 获取24小时成交量（通过K线计算）
    klines_1h_24 = client.get_klines(symbol, "1H", 24)
    if not klines_1h_24:
        logger.error("无法获取K线数据")
        return
    
    # 计算24小时成交量（USDT）
    volume_24h = sum([float(k.close) * float(k.volume) for k in klines_1h_24])
    logger.info(f"24h成交量: {volume_24h:,.0f} USDT")
    logger.info(f"要求: ≥ 30,000,000 USDT")
    logger.info(f"是否通过: {'✓' if volume_24h >= 30_000_000 else '✗'}")
    
    # 2. 获取1H K线和指标
    klines_1h = client.get_klines(symbol, "1H", 100)
    if not klines_1h:
        logger.error("无法获取1H K线")
        return
    
    df_1h = calculator.calculate_all_indicators(klines_1h, "1H")
    latest = df_1h.iloc[-1]
    prev = df_1h.iloc[-2]
    
    # 3. 检查波动率
    atr_1h = latest['atr']
    atr_pct = (atr_1h / latest['close']) * 100
    
    high_24h = max([float(k.high) for k in klines_1h[-24:]])
    low_24h = min([float(k.low) for k in klines_1h[-24:]])
    daily_range_pct = ((high_24h - low_24h) / low_24h) * 100
    
    logger.info(f"\n波动率检查:")
    logger.info(f"1H ATR: {atr_pct:.2f}%")
    logger.info(f"要求: ≥ 1.5%")
    logger.info(f"是否通过: {'✓' if atr_pct >= 1.5 else '✗'}")
    
    logger.info(f"\n日内振幅: {daily_range_pct:.2f}%")
    logger.info(f"要求: 3% - 25%")
    logger.info(f"是否通过: {'✓' if 3.0 <= daily_range_pct <= 25.0 else '✗'}")
    
    # 4. 检查趋势
    logger.info(f"\n趋势检查:")
    logger.info(f"当前价格: {latest['close']:.6f}")
    logger.info(f"MA5: {latest['ma5']:.6f}")
    logger.info(f"MA10: {latest['ma10']:.6f}")
    logger.info(f"MA20: {latest['ma20']:.6f}")
    logger.info(f"MA20方向: {'向上' if latest['ma20'] > prev['ma20'] else '向下'}")
    
    # 条件A：价格在MA20上方，且MA20方向向上
    condition_a = (latest['close'] > latest['ma20']) and (latest['ma20'] > prev['ma20'])
    logger.info(f"\n条件A（价格>MA20 且 MA20向上）: {'✓' if condition_a else '✗'}")
    
    # 条件B：MA5 > MA20
    condition_b = (latest['ma5'] > latest['ma20'])
    logger.info(f"条件B（MA5>MA20）: {'✓' if condition_b else '✗'}")
    
    # 强多头判定
    strong_bullish = (latest['ma5'] > latest['ma10'] > latest['ma20'])
    logger.info(f"强多头（MA5>MA10>MA20）: {'✓' if strong_bullish else '✗'}")
    
    trend_pass = condition_a or condition_b
    logger.info(f"\n趋势是否通过: {'✓' if trend_pass else '✗'}")
    
    # 5. 总结
    logger.info(f"\n{'='*60}")
    logger.info(f"筛选结果总结:")
    logger.info(f"{'='*60}")
    logger.info(f"24h成交量: {'✓' if volume_24h >= 30_000_000 else '✗'} ({volume_24h:,.0f} USDT)")
    logger.info(f"1H ATR: {'✓' if atr_pct >= 1.5 else '✗'} ({atr_pct:.2f}%)")
    logger.info(f"日内振幅: {'✓' if 3.0 <= daily_range_pct <= 25.0 else '✗'} ({daily_range_pct:.2f}%)")
    logger.info(f"趋势条件: {'✓' if trend_pass else '✗'}")
    
    all_pass = (
        volume_24h >= 30_000_000 and
        atr_pct >= 1.5 and
        3.0 <= daily_range_pct <= 25.0 and
        trend_pass
    )
    
    logger.info(f"\n最终结果: {'✓ 通过筛选' if all_pass else '✗ 未通过筛选'}")
    
    if not all_pass:
        logger.warning("\n未通过原因:")
        if volume_24h < 30_000_000:
            logger.warning(f"- 24h成交量不足: {volume_24h:,.0f} < 30,000,000")
        if atr_pct < 1.5:
            logger.warning(f"- 1H ATR不足: {atr_pct:.2f}% < 1.5%")
        if not (3.0 <= daily_range_pct <= 25.0):
            logger.warning(f"- 日内振幅不符: {daily_range_pct:.2f}% (要求3%-25%)")
        if not trend_pass:
            logger.warning(f"- 趋势条件不满足")

if __name__ == "__main__":
    check_uxlink()
