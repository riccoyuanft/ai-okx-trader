"""Test strategy loader functionality"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config.strategy_loader import StrategyLoader, get_strategy_loader
from src.config.prompts import get_system_prompt


def test_list_strategies():
    """Test listing available strategies"""
    print("=" * 60)
    print("测试: 列出所有可用策略")
    print("=" * 60)
    
    loader = StrategyLoader()
    strategies = loader.list_available_strategies()
    
    print(f"\n可用策略 ({len(strategies)} 个):")
    for strategy in strategies:
        print(f"  - {strategy}")
    
    assert len(strategies) >= 3, "应该至少有3个内置策略"
    print("\n✓ 测试通过\n")


def test_load_strategy(strategy_name):
    """Test loading a specific strategy"""
    print("=" * 60)
    print(f"测试: 加载策略 '{strategy_name}'")
    print("=" * 60)
    
    try:
        loader = StrategyLoader(strategy_name)
        
        # Test getting parameters
        params = loader.get_parameters()
        print(f"\n策略参数 ({len(params)} 个):")
        for key, value in params.items():
            print(f"  {key}: {value}")
        
        # Test getting sections
        description = loader.get_description()
        core_principles = loader.get_core_principles()
        strict_constraints = loader.get_strict_constraints()
        output_format = loader.get_output_format()
        
        print(f"\n策略描述长度: {len(description)} 字符")
        print(f"核心原则长度: {len(core_principles)} 字符")
        print(f"刚性约束长度: {len(strict_constraints)} 字符")
        print(f"输出格式长度: {len(output_format)} 字符")
        
        assert description, "策略描述不能为空"
        assert core_principles, "核心原则不能为空"
        assert strict_constraints, "刚性约束不能为空"
        assert output_format, "输出格式不能为空"
        
        print("\n✓ 测试通过\n")
        return True
        
    except Exception as e:
        print(f"\n✗ 测试失败: {e}\n")
        return False


def test_format_prompt(strategy_name):
    """Test formatting prompt with runtime variables"""
    print("=" * 60)
    print(f"测试: 格式化策略提示词 '{strategy_name}'")
    print("=" * 60)
    
    try:
        loader = StrategyLoader(strategy_name)
        
        # Format with runtime variables
        prompt = loader.format_prompt(
            symbol="BTC-USDT",
            initial_capital=1000.0,
            max_daily_risk_pct=8.0
        )
        
        print(f"\n生成的提示词长度: {len(prompt)} 字符")
        print("\n提示词预览 (前500字符):")
        print("-" * 60)
        print(prompt[:500])
        print("-" * 60)
        
        # Verify variables are replaced
        assert "{symbol}" not in prompt, "symbol 变量未被替换"
        assert "{initial_capital}" not in prompt, "initial_capital 变量未被替换"
        assert "BTC-USDT" in prompt, "symbol 值未正确插入"
        
        print("\n✓ 测试通过\n")
        return True
        
    except Exception as e:
        print(f"\n✗ 测试失败: {e}\n")
        import traceback
        traceback.print_exc()
        return False


def test_get_system_prompt():
    """Test the get_system_prompt function from prompts.py"""
    print("=" * 60)
    print("测试: prompts.get_system_prompt() 函数")
    print("=" * 60)
    
    try:
        prompt = get_system_prompt(symbol="ETH-USDT")
        
        print(f"\n生成的系统提示词长度: {len(prompt)} 字符")
        print("\n系统提示词预览 (前500字符):")
        print("-" * 60)
        print(prompt[:500])
        print("-" * 60)
        
        assert "ETH-USDT" in prompt, "symbol 参数未正确传递"
        assert len(prompt) > 100, "提示词长度异常"
        
        print("\n✓ 测试通过\n")
        return True
        
    except Exception as e:
        print(f"\n✗ 测试失败: {e}\n")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests"""
    print("\n" + "=" * 60)
    print("策略配置系统测试")
    print("=" * 60 + "\n")
    
    results = []
    
    # Test 1: List strategies
    try:
        test_list_strategies()
        results.append(("列出策略", True))
    except Exception as e:
        print(f"✗ 测试失败: {e}\n")
        results.append(("列出策略", False))
    
    # Test 2-4: Load each strategy
    strategies = ["15m_trend_following", "5m_scalping", "1h_swing"]
    for strategy in strategies:
        success = test_load_strategy(strategy)
        results.append((f"加载策略 {strategy}", success))
    
    # Test 5-7: Format prompt for each strategy
    for strategy in strategies:
        success = test_format_prompt(strategy)
        results.append((f"格式化提示词 {strategy}", success))
    
    # Test 8: Test get_system_prompt
    success = test_get_system_prompt()
    results.append(("get_system_prompt 函数", success))
    
    # Summary
    print("=" * 60)
    print("测试总结")
    print("=" * 60)
    
    passed = sum(1 for _, success in results if success)
    total = len(results)
    
    for test_name, success in results:
        status = "✓ 通过" if success else "✗ 失败"
        print(f"{status}: {test_name}")
    
    print(f"\n总计: {passed}/{total} 测试通过")
    
    if passed == total:
        print("\n🎉 所有测试通过!")
        return 0
    else:
        print(f"\n⚠️  {total - passed} 个测试失败")
        return 1


if __name__ == "__main__":
    exit(main())
