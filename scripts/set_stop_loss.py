"""
紧急手动设置止损止盈脚本
自动从OKX获取当前持仓信息，用户只需输入止损止盈价格
写入Redis后，运行中的bot在下个交易周期自动加载

用法:
  交互模式: python scripts/set_stop_loss.py
  快速模式: python scripts/set_stop_loss.py --sl 87.5 --tp 89.5,90.0
"""

import json
import os
import sys
import argparse

# 添加项目根目录到路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.config.settings import settings
from src.data.okx_client import OKXClient
from src.data.redis_state import RedisStateManager
from src.data.position_state import PositionStateManager


def main():
    parser = argparse.ArgumentParser(description="紧急设置止损止盈（自动获取持仓，直接写入Redis）")
    parser.add_argument("--symbol", default=settings.symbol, help=f"交易标的 (默认: {settings.symbol})")
    parser.add_argument("--sl", type=float, help="止损价格")
    parser.add_argument("--tp", type=str, help="止盈价格，多个用逗号分隔（如: 89.5,90.0）")
    parser.add_argument("--entry", type=float, help="手动指定入场价格（覆盖自动获取）")
    args = parser.parse_args()
    
    symbol = args.symbol
    
    print("=" * 60)
    print("🛡️ 紧急止损止盈设置工具")
    print("=" * 60)
    print(f"标的: {symbol}")
    
    # 1. 自动从OKX获取持仓信息
    print("\n📡 正在从OKX获取持仓信息...")
    okx = OKXClient()
    position = okx.get_position(symbol)
    current_price = okx.get_current_price(symbol)
    
    if not position.has_position:
        print("❌ OKX未检测到持仓，请确认是否已买入")
        return
    
    print(f"✅ 检测到持仓:")
    print(f"  当前价格: {current_price}")
    print(f"  持仓价值: {position.size_usdt:.2f} USDT")
    
    # 计算持仓数量（基础货币）
    base_currency = symbol.split('-')[0]
    size_btc = position.size_usdt / current_price if current_price else 0
    print(f"  持仓数量: {size_btc:.8f} {base_currency}")
    
    # 2. 确定入场价格
    # 优先级: 命令行参数 > Redis保存 > 当前价格(现货模式无法获取入场价)
    redis_state = RedisStateManager(symbol)
    saved = redis_state.load_position()
    
    entry_price = args.entry
    if not entry_price:
        if saved and saved.get('entry_price'):
            entry_price = saved['entry_price']
            print(f"  入场价(Redis): {entry_price}")
        else:
            # 现货模式无法获取入场价，需要手动输入
            print(f"\n⚠️ 无法自动获取入场价（现货模式限制）")
            while True:
                try:
                    entry_price = float(input("请输入入场价格: "))
                    if entry_price > 0:
                        break
                    print("❌ 必须大于0")
                except ValueError:
                    print("❌ 请输入数字")
    else:
        print(f"  入场价(手动): {entry_price}")
    
    pnl_pct = ((current_price - entry_price) / entry_price) * 100
    print(f"  当前盈亏: {pnl_pct:+.2f}%")
    
    # 3. 当前Redis状态
    if saved:
        old_sl = saved.get('stop_loss_price')
        old_tp = saved.get('take_profit_prices') or saved.get('take_profit_price')
        print(f"\n📋 当前Redis中SL/TP: 止损={old_sl}, 止盈={old_tp}")
    
    # 4. 输入止损价格
    stop_loss = args.sl
    if not stop_loss:
        while True:
            try:
                sl_input = input(f"\n请输入止损价格 (当前价格{current_price}): ")
                stop_loss = float(sl_input)
                if stop_loss > 0 and stop_loss < current_price:
                    break
                print(f"❌ 止损必须大于0且低于当前价格{current_price}")
            except ValueError:
                print("❌ 请输入数字")
    
    # 5. 输入止盈价格
    take_profit_prices = []
    if args.tp:
        take_profit_prices = [float(x.strip()) for x in args.tp.split(",")]
    else:
        tp_input = input(f"请输入止盈价格（多个用逗号分隔，回车跳过）: ").strip()
        if tp_input:
            take_profit_prices = [float(x.strip()) for x in tp_input.split(",")]
    
    # 6. 显示摘要
    risk = entry_price - stop_loss
    risk_pct = (risk / entry_price) * 100
    
    print("\n" + "=" * 60)
    print("设置摘要")
    print("=" * 60)
    print(f"标的: {symbol}")
    print(f"入场价: {entry_price}")
    print(f"当前价: {current_price} ({pnl_pct:+.2f}%)")
    print(f"数量: {size_btc:.8f} {base_currency} ({position.size_usdt:.2f} USDT)")
    print(f"止损: {stop_loss} (风险: {risk:.4f} / {risk_pct:.2f}%)")
    if take_profit_prices:
        for i, tp in enumerate(take_profit_prices):
            reward = tp - entry_price
            rr = reward / risk if risk > 0 else 0
            print(f"止盈{i+1}: {tp} (收益: {reward:.4f} / {(reward/entry_price*100):.2f}%, 盈亏比: {rr:.2f})")
    else:
        print("止盈: 未设置（AI将自动管理）")
    print("=" * 60)
    
    confirm = input("\n确认写入？(y/n): ")
    if confirm.lower() != 'y':
        print("❌ 已取消")
        return
    
    # 7. 写入Redis
    tp_to_save = take_profit_prices if take_profit_prices else []
    redis_state.save_position(
        entry_price=entry_price,
        size_btc=size_btc,
        stop_loss_price=stop_loss,
        take_profit_prices=tp_to_save
    )
    
    # 验证写入
    verify = redis_state.load_position()
    if verify and verify.get('stop_loss_price') == stop_loss:
        print(f"✅ Redis写入成功! 止损={verify.get('stop_loss_price')}, 止盈={verify.get('take_profit_prices')}")
    else:
        print(f"❌ Redis写入验证失败! 读取到: {verify}")
        return
    
    # 8. 同时写入文件备份
    pos_manager = PositionStateManager()
    pos_manager.save_state(
        symbol=symbol,
        entry_price=entry_price,
        size_btc=size_btc,
        stop_loss_price=stop_loss,
        take_profit_prices=tp_to_save
    )
    print("✅ 文件备份已写入")
    
    print("\n" + "=" * 60)
    print("🛡️ 止损止盈已设置！")
    print(f"  止损: {stop_loss} (价格跌到此值自动卖出)")
    if take_profit_prices:
        print(f"  止盈: {take_profit_prices}")
    print("运行中的bot将在下个交易周期自动加载（最长等待1个周期间隔）")
    print("=" * 60)


if __name__ == "__main__":
    main()
