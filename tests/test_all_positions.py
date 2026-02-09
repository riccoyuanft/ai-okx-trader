"""测试脚本：检查所有账户的持仓"""

import sys
from loguru import logger
from src.config.settings import settings
from src.data.okx_client import OKXClient

logger.remove()
logger.add(sys.stdout, level="INFO")

def main():
    print("=" * 80)
    print("全账户持仓检查")
    print("=" * 80)
    
    okx_client = OKXClient()
    
    # 1. 检查当前配置
    print("\n【当前配置】")
    print("-" * 80)
    print(f"交易对: {settings.symbol}")
    print(f"交易模式: {settings.trading_mode}")
    print(f"测试网: {settings.okx_testnet}")
    
    # 2. 查询所有持仓（不指定标的）
    print("\n【所有持仓】")
    print("-" * 80)
    try:
        # 查询所有持仓
        response = okx_client.account_api.get_positions()
        print(f"API返回码: {response['code']}")
        
        if response['code'] == '0' and response['data']:
            print(f"✓ 找到 {len(response['data'])} 个持仓:")
            for idx, pos in enumerate(response['data'], 1):
                pos_size = float(pos.get('pos', 0))
                if pos_size != 0:  # 只显示非零持仓
                    print(f"\n持仓 #{idx}:")
                    print(f"  标的: {pos.get('instId')}")
                    print(f"  持仓数量: {pos.get('pos')}")
                    print(f"  持仓方向: {pos.get('posSide')}")
                    print(f"  平均价: {pos.get('avgPx')}")
                    print(f"  未实现盈亏: {pos.get('upl')}")
                    print(f"  盈亏比: {pos.get('uplRatio')}")
                    print(f"  杠杆: {pos.get('lever')}")
                    print(f"  保证金模式: {pos.get('mgnMode')}")
        else:
            print("❌ 没有找到任何持仓")
            print(f"完整响应: {response}")
    except Exception as e:
        print(f"❌ 查询失败: {e}")
    
    # 3. 查询账户配置
    print("\n【账户配置】")
    print("-" * 80)
    try:
        config_response = okx_client.account_api.get_account_config()
        if config_response['code'] == '0':
            config = config_response['data'][0]
            print(f"账户层级: {config.get('acctLv')}")
            print(f"持仓模式: {config.get('posMode')}")
            print(f"自动借币: {config.get('autoLoan')}")
            print(f"账户权限: {config.get('level')}")
        else:
            print(f"获取配置失败: {config_response}")
    except Exception as e:
        print(f"❌ 查询账户配置失败: {e}")
    
    # 4. 查询资金账户余额
    print("\n【资金账户】")
    print("-" * 80)
    try:
        balance_response = okx_client.account_api.get_account_balance()
        if balance_response['code'] == '0' and balance_response['data']:
            details = balance_response['data'][0]['details']
            print(f"找到 {len(details)} 种资产:")
            for detail in details:
                avail = float(detail.get('availBal', 0))
                if avail > 0.01:  # 只显示余额>0.01的
                    print(f"  {detail['ccy']}: 可用={detail['availBal']}, 冻结={detail.get('frozenBal', 0)}")
        else:
            print(f"查询失败: {balance_response}")
    except Exception as e:
        print(f"❌ 查询余额失败: {e}")
    
    # 5. 查询历史订单（最近的）
    print("\n【最近订单】")
    print("-" * 80)
    try:
        order_response = okx_client.trade_api.get_orders_history(
            instType="SPOT",
            limit="10"
        )
        if order_response['code'] == '0' and order_response['data']:
            print(f"最近 {len(order_response['data'])} 笔订单:")
            for order in order_response['data'][:5]:  # 只显示前5笔
                print(f"  {order['instId']} | {order['side']} | {order['ordType']} | 状态:{order['state']} | 时间:{order['uTime']}")
        else:
            print("没有历史订单")
    except Exception as e:
        print(f"❌ 查询订单失败: {e}")
    
    print("\n" + "=" * 80)

if __name__ == "__main__":
    main()
