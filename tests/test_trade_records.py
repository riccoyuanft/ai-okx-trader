"""测试交易记录功能"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.redis_state import RedisStateManager
from src.config.settings import settings

def test_trade_records():
    """测试交易记录和统计功能"""
    
    redis_state = RedisStateManager(settings.symbol)
    
    print("\n" + "="*60)
    print("交易记录测试")
    print("="*60)
    
    # 获取交易历史
    print("\n📋 最近10笔交易记录:")
    trades = redis_state.get_trade_history(limit=10)
    
    if not trades:
        print("  暂无交易记录")
    else:
        for i, trade in enumerate(trades, 1):
            print(f"\n{i}. 交易ID: {trade['trade_id']}")
            print(f"   状态: {trade['status']}")
            print(f"   入场价: {trade['entry_price']:.4f}")
            if trade['exit_price']:
                print(f"   出场价: {trade['exit_price']:.4f}")
            print(f"   仓位: {trade['size_usdt']:.2f} USDT")
            print(f"   止损: {trade['stop_loss']:.4f}")
            print(f"   止盈: {trade['take_profit']}")
            print(f"   开仓时间: {trade['open_time']}")
            if trade['close_time']:
                print(f"   平仓时间: {trade['close_time']}")
                print(f"   平仓原因: {trade['close_reason']}")
                print(f"   盈亏: {trade['pnl_usdt']:.2f} USDT ({trade['pnl_pct']:.2f}%)")
    
    # 获取统计数据
    print("\n" + "="*60)
    print("📊 交易统计")
    print("="*60)
    
    stats = redis_state.get_trade_statistics()
    
    if stats.get('total_trades', 0) == 0:
        print("  暂无已完成交易")
    else:
        print(f"\n总交易次数: {stats['total_trades']}")
        print(f"盈利次数: {stats['win_trades']}")
        print(f"亏损次数: {stats['loss_trades']}")
        print(f"胜率: {stats['win_rate']:.2f}%")
        print(f"总盈亏: {stats['total_pnl_usdt']:.2f} USDT")
        print(f"平均盈亏: {stats['avg_pnl_usdt']:.2f} USDT")
        print(f"最大盈利: {stats['max_win_usdt']:.2f} USDT")
        print(f"最大亏损: {stats['max_loss_usdt']:.2f} USDT")
    
    print("\n" + "="*60)

if __name__ == "__main__":
    test_trade_records()
