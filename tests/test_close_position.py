"""测试平仓功能和订单金额检查"""

import sys
from loguru import logger
from src.config.settings import settings
from src.data.okx_client import OKXClient

logger.remove()
logger.add(sys.stdout, level="INFO")

def main():
    print("=" * 80)
    print("平仓功能测试")
    print("=" * 80)
    
    okx_client = OKXClient()
    
    # 1. 检查当前持仓
    print("\n【当前持仓检查】")
    print("-" * 80)
    position = okx_client.get_position(settings.symbol)
    print(f"有持仓: {position.has_position}")
    if position.has_position:
        print(f"入场价: {position.entry_price}")
        print(f"持仓价值: {position.size_usdt} USDT")
        print(f"当前盈亏: {position.current_pnl_pct}%")
    
    # 2. 检查基础货币余额
    print("\n【基础货币余额】")
    print("-" * 80)
    base_currency = settings.symbol.split('-')[0]
    balance_response = okx_client.account_api.get_account_balance(ccy=base_currency)
    
    if balance_response['code'] == '0' and balance_response['data']:
        for detail in balance_response['data'][0]['details']:
            if detail['ccy'] == base_currency:
                avail_bal = float(detail.get('availBal', 0))
                frozen_bal = float(detail.get('frozenBal', 0))
                print(f"{base_currency} 可用余额: {avail_bal}")
                print(f"{base_currency} 冻结余额: {frozen_bal}")
                print(f"{base_currency} 总余额: {avail_bal + frozen_bal}")
    
    # 3. 检查当前价格和订单金额
    print("\n【订单金额检查】")
    print("-" * 80)
    current_price = okx_client.get_current_price(settings.symbol)
    print(f"当前价格: {current_price}")
    
    if position.has_position and balance_response['code'] == '0':
        for detail in balance_response['data'][0]['details']:
            if detail['ccy'] == base_currency:
                pos_size = float(detail.get('availBal', 0))
                order_value = pos_size * current_price
                min_order_value = 5.0
                
                print(f"\n计算:")
                print(f"  数量: {pos_size} {base_currency}")
                print(f"  价格: {current_price} USDT")
                print(f"  订单金额: {order_value:.2f} USDT")
                print(f"  最小要求: {min_order_value} USDT")
                print(f"  是否满足: {'✓ 是' if order_value >= min_order_value else '✗ 否'}")
    
    # 4. 测试平仓（不实际执行）
    print("\n【平仓测试（模拟）】")
    print("-" * 80)
    if position.has_position:
        print("如果执行 close_position()，将会:")
        print(f"  1. 卖出 {pos_size} {base_currency}")
        print(f"  2. 订单类型: 市价单")
        print(f"  3. 预计成交金额: {order_value:.2f} USDT")
        
        if order_value < min_order_value:
            print(f"\n⚠️ 警告: 订单金额不足，将会失败！")
            print(f"建议: 等待价格上涨至 {min_order_value / pos_size:.6f} USDT 以上")
    else:
        print("无持仓，无需平仓")
    
    print("\n" + "=" * 80)

if __name__ == "__main__":
    main()
