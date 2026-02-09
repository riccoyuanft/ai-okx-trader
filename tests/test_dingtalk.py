"""Test DingTalk notification"""

import sys
sys.path.insert(0, 'e:/sources/trading/ai-okx-trader')

from src.notify.dingtalk import DingTalkNotifier
from src.config.settings import settings

def test_dingtalk_notification():
    """测试钉钉通知功能"""
    
    print("=" * 60)
    print("钉钉通知测试")
    print("=" * 60)
    
    # 初始化通知器
    notifier = DingTalkNotifier(
        webhook_url=settings.dingtalk_webhook if settings.dingtalk_enabled else None,
        secret=settings.dingtalk_secret
    )
    
    if not notifier.enabled:
        print("❌ 钉钉通知未启用，请检查配置")
        return
    
    print("\n1. 测试文本消息...")
    success = notifier.send_text("🤖 AI交易机器人测试消息")
    print(f"   结果: {'✅ 成功' if success else '❌ 失败'}")
    
    print("\n2. 测试交易信号通知...")
    success = notifier.notify_trade_signal(
        symbol="XAUT-USDT",
        action="long",
        price=4733.0,
        reason="测试信号：突破关键阻力位",
        stop_loss=4690.0,
        take_profit=[4750.0, 4780.0]
    )
    print(f"   结果: {'✅ 成功' if success else '❌ 失败'}")
    
    print("\n3. 测试止损通知...")
    success = notifier.notify_stop_loss(
        symbol="XAUT-USDT",
        price=4690.0,
        entry_price=4711.1,
        pnl_pct=-0.45
    )
    print(f"   结果: {'✅ 成功' if success else '❌ 失败'}")
    
    print("\n4. 测试止盈通知...")
    success = notifier.notify_take_profit(
        symbol="XAUT-USDT",
        price=4750.0,
        entry_price=4711.1,
        pnl_pct=0.83
    )
    print(f"   结果: {'✅ 成功' if success else '❌ 失败'}")
    
    print("\n5. 测试平仓通知...")
    success = notifier.notify_position_closed(
        symbol="XAUT-USDT",
        entry_price=4711.1,
        exit_price=4733.0,
        pnl_pct=0.46,
        reason="测试平仓：达到目标收益"
    )
    print(f"   结果: {'✅ 成功' if success else '❌ 失败'}")
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)

if __name__ == "__main__":
    test_dingtalk_notification()
