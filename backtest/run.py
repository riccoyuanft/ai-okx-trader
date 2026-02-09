"""
回测命令行入口
快速运行回测并生成报告
"""

import argparse
from datetime import datetime
from typing import Dict
from loguru import logger

from src.data.okx_client import OKXClient
from src.config import settings
from backtest.engine import BacktestEngine
from backtest.analyzer import BacktestAnalyzer
from backtest.data.loader import HistoricalDataLoader


def main():
    """命令行入口"""
    parser = argparse.ArgumentParser(description="AI交易策略回测工具")
    
    parser.add_argument(
        "--start-date",
        type=str,
        required=True,
        help="开始日期，格式: YYYY-MM-DD"
    )
    
    parser.add_argument(
        "--end-date",
        type=str,
        required=True,
        help="结束日期，格式: YYYY-MM-DD"
    )
    
    parser.add_argument(
        "--initial-capital",
        type=float,
        default=10000,
        help="初始资金（USDT），默认: 10000"
    )
    
    parser.add_argument(
        "--symbol",
        type=str,
        default="XAUT-USDT",
        help="交易对，默认: XAUT-USDT"
    )
    
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="不使用缓存，重新从API获取数据"
    )
    
    args = parser.parse_args()
    
    # 验证日期格式
    try:
        datetime.strptime(args.start_date, "%Y-%m-%d")
        datetime.strptime(args.end_date, "%Y-%m-%d")
    except ValueError:
        logger.error("日期格式错误，请使用 YYYY-MM-DD 格式")
        return
    
    logger.info("="*60)
    logger.info("AI交易策略回测工具")
    logger.info("="*60)
    logger.info(f"交易对: {args.symbol}")
    logger.info(f"回测周期: {args.start_date} ~ {args.end_date}")
    logger.info(f"初始资金: {args.initial_capital} USDT")
    logger.info("="*60)
    
    # 初始化组件
    okx_client = OKXClient(
        api_key=settings.okx_api_key,
        secret_key=settings.okx_secret_key,
        passphrase=settings.okx_passphrase,
        testnet=settings.testnet
    )
    
    data_loader = HistoricalDataLoader(okx_client)
    
    # 创建回测引擎
    engine = BacktestEngine(
        start_date=args.start_date,
        end_date=args.end_date,
        initial_capital=args.initial_capital,
        symbol=args.symbol,
        data_loader=data_loader
    )
    
    # 执行回测
    result = engine.run()
    
    # 分析结果
    analyzer = BacktestAnalyzer()
    analysis = analyzer.analyze(result)
    
    # 打印报告
    analyzer.print_summary(analysis)
    
    # 保存详细报告
    save_report(analysis, result)
    
    logger.info("✓ 回测完成！")


def save_report(analysis: Dict, result: Dict):
    """保存详细报告到文件"""
    import json
    from pathlib import Path
    
    # 创建报告目录
    report_dir = Path("backtest/reports")
    report_dir.mkdir(parents=True, exist_ok=True)
    
    # 生成报告文件名
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    config = analysis["config"]
    filename = f"backtest_{config['symbol']}_{config['start_date']}_{config['end_date']}_{timestamp}.json"
    filepath = report_dir / filename
    
    # 保存完整数据
    report_data = {
        "analysis": analysis,
        "trades": result["trades"],
        "equity_curve": result["equity_curve"]
    }
    
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(report_data, f, ensure_ascii=False, indent=2)
    
    logger.info(f"✓ 详细报告已保存: {filepath}")


if __name__ == "__main__":
    main()
