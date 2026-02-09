"""测试脚本：检查持仓状态"""

import sys
from loguru import logger
from src.config.settings import settings
from src.data.okx_client import OKXClient
from src.data.redis_state import RedisStateManager
from src.data.position_state import PositionStateManager

logger.remove()
logger.add(sys.stdout, level="INFO")

def main():
    print("=" * 80)
    print("持仓状态诊断测试")
    print("=" * 80)
    
    # 1. 检查OKX实际持仓
    print("\n【1】检查OKX交易所实际持仓")
    print("-" * 80)
    okx_client = OKXClient()
    position = okx_client.get_position(settings.symbol)
    
    print(f"交易对: {settings.symbol}")
    print(f"有持仓: {position.has_position}")
    if position.has_position:
        print(f"入场价格: {position.entry_price}")
        print(f"持仓金额: {position.size_usdt} USDT")
        print(f"当前盈亏: {position.current_pnl_pct:.2f}%")
        print(f"入场时间: {position.entry_time}")
    else:
        print("❌ OKX交易所显示无持仓")
    
    # 2. 检查Redis状态
    print("\n【2】检查Redis持仓状态")
    print("-" * 80)
    redis_state = RedisStateManager(settings.symbol)
    saved_position = redis_state.load_position()
    
    if saved_position:
        print(f"✓ Redis中有持仓记录:")
        print(f"  标的: {saved_position.get('symbol')}")
        print(f"  入场价格: {saved_position.get('entry_price')}")
        print(f"  持仓数量: {saved_position.get('size_btc')} 币")
        print(f"  止损价格: {saved_position.get('stop_loss_price')}")
        print(f"  止盈价格: {saved_position.get('take_profit_price')}")
    else:
        print("❌ Redis中无持仓记录")
    
    # 3. 检查文件状态
    print("\n【3】检查文件持仓状态")
    print("-" * 80)
    position_manager = PositionStateManager()
    file_state = position_manager.load_state()
    
    if file_state:
        print(f"✓ 文件中有持仓记录:")
        print(f"  入场价格: {file_state.get('entry_price')}")
        print(f"  持仓数量: {file_state.get('size_btc')} 币")
        print(f"  止损价格: {file_state.get('stop_loss_price')}")
        print(f"  止盈价格: {file_state.get('take_profit_price')}")
    else:
        print("❌ 文件中无持仓记录")
    
    # 4. 获取账户余额
    print("\n【4】检查账户余额")
    print("-" * 80)
    balance = okx_client.get_balance("USDT")
    print(f"USDT可用余额: {balance}")
    
    # 5. 获取原始API响应
    print("\n【5】OKX原始持仓API响应")
    print("-" * 80)
    try:
        response = okx_client.account_api.get_positions(instId=settings.symbol)
        print(f"API返回码: {response['code']}")
        print(f"API消息: {response.get('msg', 'OK')}")
        print(f"持仓数据: {response.get('data', [])}")
        
        if response['data']:
            for pos in response['data']:
                print(f"\n持仓详情:")
                print(f"  pos (持仓数量): {pos.get('pos')}")
                print(f"  avgPx (平均价): {pos.get('avgPx')}")
                print(f"  upl (未实现盈亏): {pos.get('upl')}")
                print(f"  uplRatio (盈亏比): {pos.get('uplRatio')}")
                print(f"  lever (杠杆): {pos.get('lever')}")
                print(f"  notionalUsd (名义价值USD): {pos.get('notionalUsd')}")
    except Exception as e:
        print(f"❌ 获取原始API响应失败: {e}")
    
    # 6. 诊断结论
    print("\n" + "=" * 80)
    print("【诊断结论】")
    print("=" * 80)
    
    if position.has_position:
        print("✓ OKX交易所有实际持仓")
        if not saved_position:
            print("⚠️ 但Redis中无持仓记录 - 这是问题所在！")
            print("   原因：程序重启后没有从OKX同步持仓状态")
            print("   解决：需要在启动时检查OKX实际持仓并同步到Redis")
    else:
        print("❌ OKX交易所无实际持仓")
        if saved_position:
            print("⚠️ 但Redis中有持仓记录 - 数据不一致！")
            print("   原因：可能已平仓但Redis未清除")
            print("   解决：清除Redis中的过期持仓记录")
    
    print("=" * 80)

if __name__ == "__main__":
    main()
