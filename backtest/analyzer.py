"""
回测性能分析器
计算各种性能指标和统计数据
"""

import numpy as np
from typing import List, Dict
from datetime import datetime
from loguru import logger


class BacktestAnalyzer:
    """回测性能分析器"""
    
    def __init__(self):
        """初始化分析器"""
        logger.info("性能分析器已初始化")
    
    def analyze(self, result: Dict) -> Dict:
        """
        分析回测结果
        
        Args:
            result: 回测引擎返回的结果字典
        
        Returns:
            包含详细性能指标的字典
        """
        trades = result["trades"]
        equity_curve = result["equity_curve"]
        config = result["config"]
        
        if not trades:
            logger.warning("没有交易记录，无法进行分析")
            return self._empty_analysis(config)
        
        # 基础指标
        basic_metrics = self._calculate_basic_metrics(trades, config)
        
        # 风险指标
        risk_metrics = self._calculate_risk_metrics(trades, equity_curve, config)
        
        # 交易统计
        trade_stats = self._calculate_trade_stats(trades)
        
        # 时间分析
        time_analysis = self._calculate_time_analysis(trades)
        
        # 合并所有指标
        analysis = {
            **basic_metrics,
            **risk_metrics,
            **trade_stats,
            **time_analysis,
            "config": config
        }
        
        logger.info("✓ 性能分析完成")
        return analysis
    
    def _calculate_basic_metrics(self, trades: List[Dict], config: Dict) -> Dict:
        """计算基础性能指标"""
        total_trades = len(trades)
        winning_trades = [t for t in trades if t["pnl"] > 0]
        losing_trades = [t for t in trades if t["pnl"] < 0]
        
        win_count = len(winning_trades)
        loss_count = len(losing_trades)
        win_rate = (win_count / total_trades * 100) if total_trades > 0 else 0
        
        total_pnl = sum(t["pnl"] for t in trades)
        total_pnl_pct = (total_pnl / config["initial_capital"]) * 100
        
        return {
            "total_trades": total_trades,
            "winning_trades": win_count,
            "losing_trades": loss_count,
            "win_rate": round(win_rate, 2),
            "total_pnl": round(total_pnl, 2),
            "total_pnl_pct": round(total_pnl_pct, 2),
            "final_capital": round(config["initial_capital"] + total_pnl, 2)
        }
    
    def _calculate_risk_metrics(
        self,
        trades: List[Dict],
        equity_curve: List[Dict],
        config: Dict
    ) -> Dict:
        """计算风险指标"""
        # 最大回撤
        max_drawdown, max_dd_pct = self._calc_max_drawdown(equity_curve)
        
        # 夏普比率
        sharpe_ratio = self._calc_sharpe_ratio(equity_curve, config["initial_capital"])
        
        # 盈利因子
        total_profit = sum(t["pnl"] for t in trades if t["pnl"] > 0)
        total_loss = abs(sum(t["pnl"] for t in trades if t["pnl"] < 0))
        profit_factor = (total_profit / total_loss) if total_loss > 0 else float('inf')
        
        return {
            "max_drawdown": round(max_drawdown, 2),
            "max_drawdown_pct": round(max_dd_pct, 2),
            "sharpe_ratio": round(sharpe_ratio, 2),
            "profit_factor": round(profit_factor, 2)
        }
    
    def _calculate_trade_stats(self, trades: List[Dict]) -> Dict:
        """计算交易统计"""
        winning_trades = [t for t in trades if t["pnl"] > 0]
        losing_trades = [t for t in trades if t["pnl"] < 0]
        
        # 平均盈亏
        avg_win = np.mean([t["pnl"] for t in winning_trades]) if winning_trades else 0
        avg_loss = np.mean([t["pnl"] for t in losing_trades]) if losing_trades else 0
        avg_win_pct = np.mean([t["pnl_pct"] for t in winning_trades]) if winning_trades else 0
        avg_loss_pct = np.mean([t["pnl_pct"] for t in losing_trades]) if losing_trades else 0
        
        # 最大单笔盈亏
        largest_win = max([t["pnl"] for t in trades]) if trades else 0
        largest_loss = min([t["pnl"] for t in trades]) if trades else 0
        largest_win_pct = max([t["pnl_pct"] for t in trades]) if trades else 0
        largest_loss_pct = min([t["pnl_pct"] for t in trades]) if trades else 0
        
        # 连续盈亏
        max_consecutive_wins = self._calc_max_consecutive(trades, True)
        max_consecutive_losses = self._calc_max_consecutive(trades, False)
        
        # 平仓原因统计
        exit_reasons = {}
        for trade in trades:
            reason = trade.get("exit_reason", "unknown")
            exit_reasons[reason] = exit_reasons.get(reason, 0) + 1
        
        return {
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "avg_win_pct": round(avg_win_pct, 2),
            "avg_loss_pct": round(avg_loss_pct, 2),
            "largest_win": round(largest_win, 2),
            "largest_loss": round(largest_loss, 2),
            "largest_win_pct": round(largest_win_pct, 2),
            "largest_loss_pct": round(largest_loss_pct, 2),
            "max_consecutive_wins": max_consecutive_wins,
            "max_consecutive_losses": max_consecutive_losses,
            "exit_reasons": exit_reasons
        }
    
    def _calculate_time_analysis(self, trades: List[Dict]) -> Dict:
        """计算时间相关分析"""
        if not trades:
            return {
                "avg_holding_time_minutes": 0,
                "total_trading_days": 0
            }
        
        # 平均持仓时间（分钟）
        holding_times = [t["holding_time"] / (1000 * 60) for t in trades]
        avg_holding_time = np.mean(holding_times)
        
        # 交易天数
        start_time = min(t["entry_time"] for t in trades)
        end_time = max(t["exit_time"] for t in trades)
        total_days = (end_time - start_time) / (1000 * 60 * 60 * 24)
        
        return {
            "avg_holding_time_minutes": round(avg_holding_time, 2),
            "total_trading_days": round(total_days, 2)
        }
    
    def _calc_max_drawdown(self, equity_curve: List[Dict]) -> tuple:
        """计算最大回撤"""
        if not equity_curve:
            return 0, 0
        
        equities = [e["equity"] for e in equity_curve]
        peak = equities[0]
        max_dd = 0
        max_dd_pct = 0
        
        for equity in equities:
            if equity > peak:
                peak = equity
            
            dd = peak - equity
            dd_pct = (dd / peak) * 100 if peak > 0 else 0
            
            if dd > max_dd:
                max_dd = dd
                max_dd_pct = dd_pct
        
        return max_dd, max_dd_pct
    
    def _calc_sharpe_ratio(self, equity_curve: List[Dict], initial_capital: float) -> float:
        """计算夏普比率（年化）"""
        if len(equity_curve) < 2:
            return 0
        
        # 计算每日收益率
        equities = [e["equity"] for e in equity_curve]
        returns = []
        
        for i in range(1, len(equities)):
            daily_return = (equities[i] - equities[i-1]) / equities[i-1]
            returns.append(daily_return)
        
        if not returns:
            return 0
        
        # 平均收益率和标准差
        avg_return = np.mean(returns)
        std_return = np.std(returns)
        
        if std_return == 0:
            return 0
        
        # 年化夏普比率（假设无风险利率为0）
        # 5分钟K线，一天288根，一年约105120根
        periods_per_year = 105120
        sharpe = (avg_return / std_return) * np.sqrt(periods_per_year)
        
        return sharpe
    
    def _calc_max_consecutive(self, trades: List[Dict], is_win: bool) -> int:
        """计算最大连续盈利/亏损次数"""
        max_consecutive = 0
        current_consecutive = 0
        
        for trade in trades:
            if (is_win and trade["pnl"] > 0) or (not is_win and trade["pnl"] < 0):
                current_consecutive += 1
                max_consecutive = max(max_consecutive, current_consecutive)
            else:
                current_consecutive = 0
        
        return max_consecutive
    
    def _empty_analysis(self, config: Dict) -> Dict:
        """返回空分析结果"""
        return {
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "win_rate": 0,
            "total_pnl": 0,
            "total_pnl_pct": 0,
            "final_capital": config["initial_capital"],
            "max_drawdown": 0,
            "max_drawdown_pct": 0,
            "sharpe_ratio": 0,
            "profit_factor": 0,
            "config": config
        }
    
    def print_summary(self, analysis: Dict):
        """打印分析摘要"""
        print("\n" + "="*60)
        print("回测报告")
        print("="*60)
        
        config = analysis["config"]
        print(f"回测周期: {config['start_date']} 至 {config['end_date']}")
        print(f"交易对: {config['symbol']}")
        print(f"初始资金: {config['initial_capital']:,.2f} USDT")
        print(f"最终资金: {analysis['final_capital']:,.2f} USDT")
        print(f"总收益: {analysis['total_pnl']:+,.2f} USDT ({analysis['total_pnl_pct']:+.2f}%)")
        
        print(f"\n交易统计:")
        print(f"  总交易次数: {analysis['total_trades']}")
        print(f"  盈利交易: {analysis['winning_trades']} ({analysis['win_rate']:.2f}%)")
        print(f"  亏损交易: {analysis['losing_trades']}")
        
        if analysis.get('avg_win'):
            print(f"  平均盈利: {analysis['avg_win']:+.2f} USDT ({analysis['avg_win_pct']:+.2f}%)")
            print(f"  平均亏损: {analysis['avg_loss']:+.2f} USDT ({analysis['avg_loss_pct']:+.2f}%)")
            print(f"  盈亏比: {abs(analysis['avg_win']/analysis['avg_loss']):.2f}" if analysis['avg_loss'] != 0 else "  盈亏比: N/A")
        
        print(f"\n风险指标:")
        print(f"  最大回撤: {analysis['max_drawdown']:.2f} USDT ({analysis['max_drawdown_pct']:.2f}%)")
        print(f"  夏普比率: {analysis['sharpe_ratio']:.2f}")
        print(f"  盈利因子: {analysis['profit_factor']:.2f}")
        
        if analysis.get('largest_win'):
            print(f"\n最佳/最差交易:")
            print(f"  最佳交易: {analysis['largest_win']:+.2f} USDT ({analysis['largest_win_pct']:+.2f}%)")
            print(f"  最差交易: {analysis['largest_loss']:+.2f} USDT ({analysis['largest_loss_pct']:+.2f}%)")
        
        if analysis.get('max_consecutive_wins'):
            print(f"\n连续性:")
            print(f"  最长连胜: {analysis['max_consecutive_wins']}次")
            print(f"  最长连亏: {analysis['max_consecutive_losses']}次")
        
        if analysis.get('exit_reasons'):
            print(f"\n平仓原因:")
            for reason, count in analysis['exit_reasons'].items():
                print(f"  {reason}: {count}次")
        
        print("="*60 + "\n")
