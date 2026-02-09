"""
交易模拟器
模拟真实交易执行，包括手续费、滑点、止损止盈等
"""

from datetime import datetime
from typing import Optional, Dict
from loguru import logger


class TradeSimulator:
    """交易执行模拟器"""
    
    def __init__(
        self,
        fee_rate: float = 0.001,  # 手续费率 0.1%
        slippage: float = 0.0001   # 滑点 0.01%
    ):
        """
        初始化交易模拟器
        
        Args:
            fee_rate: 手续费率（默认0.1%，OKX现货标准费率）
            slippage: 滑点率（默认0.01%）
        """
        self.fee_rate = fee_rate
        self.slippage = slippage
        logger.info(f"交易模拟器已初始化 (手续费:{fee_rate*100}%, 滑点:{slippage*100}%)")
    
    def execute_long(
        self,
        timestamp: int,
        price: float,
        size_usdt: float,
        stop_loss_price: float,
        take_profit_price: float
    ) -> Dict:
        """
        模拟开多仓
        
        Args:
            timestamp: 时间戳
            price: 开仓价格
            size_usdt: 仓位大小（USDT）
            stop_loss_price: 止损价格
            take_profit_price: 止盈价格
        
        Returns:
            交易记录字典
        """
        # 考虑滑点
        actual_price = price * (1 + self.slippage)
        
        # 计算手续费
        fee = size_usdt * self.fee_rate
        
        # 实际使用的资金（包含手续费）
        total_cost = size_usdt + fee
        
        # 实际持仓数量
        size_coin = size_usdt / actual_price
        
        trade = {
            "type": "long",
            "entry_time": timestamp,
            "entry_price": actual_price,
            "size_usdt": size_usdt,
            "size_coin": size_coin,
            "stop_loss": stop_loss_price,
            "take_profit": take_profit_price,
            "entry_fee": fee,
            "total_cost": total_cost,
            "exit_time": None,
            "exit_price": None,
            "exit_fee": None,
            "exit_reason": None,
            "pnl": None,
            "pnl_pct": None,
            "status": "open"
        }
        
        logger.debug(f"开仓: 价格={actual_price:.4f}, 数量={size_coin:.6f}, 止损={stop_loss_price:.4f}, 止盈={take_profit_price:.4f}")
        
        return trade
    
    def check_exit(
        self,
        trade: Dict,
        current_time: int,
        current_price: float,
        high_price: float,
        low_price: float
    ) -> Optional[str]:
        """
        检查是否触发平仓条件
        
        Args:
            trade: 交易记录
            current_time: 当前时间戳
            current_price: 当前价格
            high_price: 当前K线最高价
            low_price: 当前K线最低价
        
        Returns:
            平仓原因：'stop_loss', 'take_profit', 'signal', None
        """
        if trade["status"] != "open":
            return None
        
        # 检查止损（使用最低价）
        if low_price <= trade["stop_loss"]:
            return "stop_loss"
        
        # 检查止盈（使用最高价）
        if high_price >= trade["take_profit"]:
            return "take_profit"
        
        return None
    
    def execute_close(
        self,
        trade: Dict,
        timestamp: int,
        price: float,
        reason: str
    ) -> Dict:
        """
        模拟平仓
        
        Args:
            trade: 交易记录
            timestamp: 平仓时间戳
            price: 平仓价格
            reason: 平仓原因
        
        Returns:
            更新后的交易记录
        """
        # 考虑滑点
        if reason == "stop_loss":
            # 止损时滑点不利
            actual_price = price * (1 - self.slippage)
        elif reason == "take_profit":
            # 止盈时滑点不利
            actual_price = price * (1 - self.slippage)
        else:
            # 信号平仓
            actual_price = price * (1 - self.slippage)
        
        # 计算平仓金额
        exit_value = trade["size_coin"] * actual_price
        
        # 计算平仓手续费
        exit_fee = exit_value * self.fee_rate
        
        # 计算净收益
        net_proceeds = exit_value - exit_fee
        pnl = net_proceeds - trade["total_cost"]
        pnl_pct = (pnl / trade["total_cost"]) * 100
        
        # 更新交易记录
        trade.update({
            "exit_time": timestamp,
            "exit_price": actual_price,
            "exit_fee": exit_fee,
            "exit_reason": reason,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "status": "closed",
            "holding_time": timestamp - trade["entry_time"]
        })
        
        logger.debug(
            f"平仓: 原因={reason}, 价格={actual_price:.4f}, "
            f"盈亏={pnl:.2f} USDT ({pnl_pct:+.2f}%)"
        )
        
        return trade
    
    def execute_signal_close(
        self,
        trade: Dict,
        timestamp: int,
        price: float
    ) -> Dict:
        """
        根据AI信号平仓
        
        Args:
            trade: 交易记录
            timestamp: 平仓时间戳
            price: 平仓价格
        
        Returns:
            更新后的交易记录
        """
        return self.execute_close(trade, timestamp, price, "signal")
    
    def calculate_position_value(
        self,
        trade: Dict,
        current_price: float
    ) -> Dict:
        """
        计算当前持仓价值和浮动盈亏
        
        Args:
            trade: 交易记录
            current_price: 当前价格
        
        Returns:
            包含持仓价值和浮动盈亏的字典
        """
        if trade["status"] != "open":
            return {
                "position_value": 0,
                "unrealized_pnl": 0,
                "unrealized_pnl_pct": 0
            }
        
        # 当前持仓价值
        position_value = trade["size_coin"] * current_price
        
        # 浮动盈亏（未扣除平仓手续费）
        unrealized_pnl = position_value - trade["total_cost"]
        unrealized_pnl_pct = (unrealized_pnl / trade["total_cost"]) * 100
        
        return {
            "position_value": position_value,
            "unrealized_pnl": unrealized_pnl,
            "unrealized_pnl_pct": unrealized_pnl_pct
        }
