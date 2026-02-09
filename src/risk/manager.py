"""Risk management module"""

from datetime import datetime, timedelta
from typing import Dict, List
from loguru import logger

from src.config.settings import settings
from src.data.models import AIDecision, MarketData


class RiskManager:
    """风控管理器"""
    
    def __init__(self):
        self.daily_trades: List[Dict] = []
        self.consecutive_losses = 0
        self.total_daily_risk = 0.0
        self.last_reset_date = datetime.now().date()
        
        logger.info("Risk Manager initialized")
    
    def validate_decision(self, decision: AIDecision, market_data: MarketData) -> tuple[bool, str]:
        """
        验证决策是否符合风控规则
        
        Args:
            decision: AI决策
            market_data: 市场数据
        
        Returns:
            (是否通过验证, 拒绝原因)
        """
        self._reset_daily_stats_if_needed()
        
        if decision.d == "wait":
            return True, ""
        
        if decision.d == "close":
            return True, ""
        
        if decision.d == "long":
            passed, reason = self._validate_long_decision(decision, market_data)
            if not passed:
                return False, reason
        
        return True, ""
    
    def _validate_long_decision(self, decision: AIDecision, market_data: MarketData) -> tuple[bool, str]:
        """验证开多决策，返回(是否通过, 拒绝原因)"""
        if decision.e is None or decision.sl is None or decision.tp is None:
            reason = "缺少必要字段（入场价/止损/止盈）"
            logger.warning("Missing required fields in long decision")
            return False, reason
        
        # 解析入场价格（支持区间格式）
        entry_min, entry_max = decision.get_entry_price_range()
        if entry_min is None or entry_max is None:
            reason = f"入场价格格式无效: {decision.e}"
            logger.warning(f"Invalid entry price format: {decision.e}")
            return False, reason
        entry_price = (entry_min + entry_max) / 2
        
        if entry_price >= market_data.current_price * 1.02:
            reason = f"入场价过高: {entry_price:.4f} (当前价 {market_data.current_price:.4f})"
            logger.warning(f"Entry price too high: {entry_price} vs current {market_data.current_price}")
            return False, reason
        
        if decision.sl >= entry_price:
            reason = f"止损价必须低于入场价: 止损={decision.sl:.4f}, 入场={entry_price:.4f}"
            logger.warning(f"Stop loss must be below entry: sl={decision.sl}, entry={entry_price}")
            return False, reason
        
        # 检查止损间距是否过小（防止秒触发止损）
        sl_distance_pct = (entry_price - decision.sl) / entry_price * 100
        min_sl_pct = settings.initial_sl_min_distance_pct
        if sl_distance_pct < min_sl_pct:
            logger.warning(
                f"⚠️ 止损间距过小: {sl_distance_pct:.3f}% < {min_sl_pct}%, "
                f"将在成交后自动拓宽至{min_sl_pct}% (入场≈{entry_price:.6f}, AI止损={decision.sl:.6f})"
            )
        
        risk_reward_ratio = self._calculate_risk_reward_ratio(decision)
        # 使用容差比较避免浮点数精度问题（容差0.01）
        tolerance = 0.01
        if risk_reward_ratio < settings.min_risk_reward_ratio - tolerance:
            reason = f"盈亏比过低: {risk_reward_ratio:.2f} < {settings.min_risk_reward_ratio}"
            logger.warning(f"Risk/reward ratio too low: {risk_reward_ratio:.2f} < {settings.min_risk_reward_ratio}")
            return False, reason
        elif risk_reward_ratio < settings.min_risk_reward_ratio:
            logger.info(f"Risk/reward ratio borderline: {risk_reward_ratio:.2f} ≈ {settings.min_risk_reward_ratio} (within tolerance, passed)")
        else:
            logger.info(f"Risk/reward ratio: {risk_reward_ratio:.2f} ≥ {settings.min_risk_reward_ratio} ✓")
        
        position_risk = abs(entry_price - decision.sl) / entry_price * 100
        if self.total_daily_risk + position_risk > market_data.max_daily_risk_pct:
            total_risk = self.total_daily_risk + position_risk
            reason = f"每日风险限额超标: {total_risk:.2f}% > {market_data.max_daily_risk_pct}% (已用{self.total_daily_risk:.2f}% + 本次{position_risk:.2f}%)"
            logger.warning(f"Daily risk limit exceeded: {total_risk:.2f}%")
            return False, reason
        
        if self.consecutive_losses >= settings.max_consecutive_losses:
            max_position = settings.loss_protection_position_pct
            if decision.s > max_position:
                logger.warning(f"Position size reduced due to consecutive losses: {decision.s}% -> {max_position}%")
                decision.s = max_position
        
        logger.info(f"Decision validated: {decision.d}, risk/reward={risk_reward_ratio:.2f}")
        return True, ""
    
    def _calculate_risk_reward_ratio(self, decision: AIDecision) -> float:
        """计算盈亏比（支持区间入场价格）"""
        if not decision.e or not decision.sl or not decision.tp:
            return 0.0
        
        # 解析入场价格（支持区间格式）
        entry_min, entry_max = decision.get_entry_price_range()
        if entry_min is None or entry_max is None:
            return 0.0
        entry_price = (entry_min + entry_max) / 2
        
        risk = entry_price - decision.sl
        reward = decision.tp[0] - entry_price
        
        if risk <= 0:
            return 0.0
        
        return reward / risk
    
    def record_trade(self, decision: AIDecision, pnl: float):
        """记录交易结果"""
        self._reset_daily_stats_if_needed()
        
        trade = {
            "timestamp": datetime.now(),
            "decision": decision.d,
            "pnl": pnl
        }
        
        self.daily_trades.append(trade)
        
        if pnl < 0:
            self.consecutive_losses += 1
            position_risk = abs(pnl)
            self.total_daily_risk += position_risk
        else:
            self.consecutive_losses = 0
        
        logger.info(f"Trade recorded: pnl={pnl:.2f}, consecutive_losses={self.consecutive_losses}")
    
    def _reset_daily_stats_if_needed(self):
        """每日重置统计"""
        today = datetime.now().date()
        
        if today > self.last_reset_date:
            logger.info(f"Resetting daily stats (previous date: {self.last_reset_date})")
            self.daily_trades = []
            self.total_daily_risk = 0.0
            self.last_reset_date = today
    
    def get_daily_summary(self) -> Dict:
        """获取当日统计摘要"""
        total_trades = len(self.daily_trades)
        winning_trades = sum(1 for t in self.daily_trades if t['pnl'] > 0)
        total_pnl = sum(t['pnl'] for t in self.daily_trades)
        
        return {
            "date": self.last_reset_date,
            "total_trades": total_trades,
            "winning_trades": winning_trades,
            "win_rate": winning_trades / total_trades if total_trades > 0 else 0,
            "total_pnl": total_pnl,
            "total_risk_used": self.total_daily_risk,
            "consecutive_losses": self.consecutive_losses
        }
