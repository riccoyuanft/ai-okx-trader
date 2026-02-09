"""
回测引擎核心
执行历史数据回测，模拟真实交易流程
"""

from datetime import datetime
from typing import List, Dict, Optional
from loguru import logger

from src.ai.agent import AIAgent
from src.indicators.ta_calculator import TACalculator
from src.data.models import MarketData, Position, KeyLevels
from src.config import settings
from backtest.simulator import TradeSimulator
from backtest.data.loader import HistoricalDataLoader


class BacktestEngine:
    """回测引擎"""
    
    def __init__(
        self,
        start_date: str,
        end_date: str,
        initial_capital: float,
        symbol: str = "XAUT-USDT",
        data_loader: Optional[HistoricalDataLoader] = None
    ):
        """
        初始化回测引擎
        
        Args:
            start_date: 开始日期 "YYYY-MM-DD"
            end_date: 结束日期 "YYYY-MM-DD"
            initial_capital: 初始资金
            symbol: 交易对
            data_loader: 数据加载器（可选）
        """
        self.start_date = start_date
        self.end_date = end_date
        self.initial_capital = initial_capital
        self.symbol = symbol
        
        # 复用实盘组件
        self.ai_agent = AIAgent()
        self.ta_calculator = TACalculator()
        self.simulator = TradeSimulator()
        self.data_loader = data_loader
        
        # 回测状态
        self.current_capital = initial_capital
        self.trades: List[Dict] = []
        self.equity_curve: List[Dict] = []
        self.current_position: Optional[Dict] = None
        
        logger.info(f"回测引擎已初始化: {symbol} {start_date} ~ {end_date}")
        logger.info(f"初始资金: {initial_capital} USDT")
    
    def run(self) -> Dict:
        """
        执行回测
        
        Returns:
            回测结果字典
        """
        logger.info("="*60)
        logger.info("开始回测...")
        logger.info("="*60)
        
        # 1. 加载历史数据
        logger.info("正在加载历史数据...")
        klines_5m = self.data_loader.load_klines(
            self.symbol, "5m", self.start_date, self.end_date
        )
        klines_15m = self.data_loader.load_klines(
            self.symbol, "15m", self.start_date, self.end_date
        )
        klines_1h = self.data_loader.load_klines(
            self.symbol, "1H", self.start_date, self.end_date
        )
        
        if not klines_5m:
            logger.error("未能加载5分钟K线数据")
            return self._generate_empty_result()
        
        logger.info(f"✓ 5m K线: {len(klines_5m)} 根")
        logger.info(f"✓ 15m K线: {len(klines_15m)} 根")
        logger.info(f"✓ 1h K线: {len(klines_1h)} 根")
        
        # 2. 按5分钟K线时间顺序遍历
        logger.info("开始模拟交易...")
        total_bars = len(klines_5m)
        
        for i in range(120, total_bars):  # 从第120根开始，确保有足够的历史数据
            current_kline = klines_5m[i]
            
            # 检查是否触发止损/止盈
            if self.current_position:
                exit_reason = self.simulator.check_exit(
                    self.current_position,
                    current_kline.timestamp,
                    current_kline.close,
                    current_kline.high,
                    current_kline.low
                )
                
                if exit_reason:
                    # 执行平仓
                    exit_price = (
                        self.current_position["stop_loss"]
                        if exit_reason == "stop_loss"
                        else self.current_position["take_profit"]
                    )
                    
                    closed_trade = self.simulator.execute_close(
                        self.current_position,
                        current_kline.timestamp,
                        exit_price,
                        exit_reason
                    )
                    
                    # 更新资金
                    self.current_capital += closed_trade["pnl"]
                    
                    # 记录交易
                    self.trades.append(closed_trade)
                    self.current_position = None
                    
                    logger.info(
                        f"[{i}/{total_bars}] 平仓: {exit_reason}, "
                        f"盈亏={closed_trade['pnl']:.2f} USDT ({closed_trade['pnl_pct']:+.2f}%)"
                    )
            
            # 每5根K线（25分钟）执行一次AI决策
            if i % 5 == 0:
                # 构建市场数据快照
                market_data = self._build_market_snapshot(
                    i, klines_5m, klines_15m, klines_1h
                )
                
                # AI决策
                decision = self.ai_agent.make_decision(market_data)
                
                # 执行决策
                if decision.d == "long" and not self.current_position:
                    # 开仓
                    size_usdt = self.current_capital * (settings.max_daily_risk_pct / 100)
                    stop_loss_price = current_kline.close * (1 - settings.stop_loss_pct / 100)
                    take_profit_price = current_kline.close * (1 + settings.take_profit_pct / 100)
                    
                    self.current_position = self.simulator.execute_long(
                        current_kline.timestamp,
                        current_kline.close,
                        size_usdt,
                        stop_loss_price,
                        take_profit_price
                    )
                    
                    # 扣除开仓成本
                    self.current_capital -= self.current_position["total_cost"]
                    
                    logger.info(
                        f"[{i}/{total_bars}] 开仓: 价格={current_kline.close:.4f}, "
                        f"仓位={size_usdt:.2f} USDT"
                    )
                
                elif decision.d == "close" and self.current_position:
                    # 信号平仓
                    closed_trade = self.simulator.execute_signal_close(
                        self.current_position,
                        current_kline.timestamp,
                        current_kline.close
                    )
                    
                    # 更新资金
                    self.current_capital += closed_trade["pnl"]
                    
                    # 记录交易
                    self.trades.append(closed_trade)
                    self.current_position = None
                    
                    logger.info(
                        f"[{i}/{total_bars}] 信号平仓: "
                        f"盈亏={closed_trade['pnl']:.2f} USDT ({closed_trade['pnl_pct']:+.2f}%)"
                    )
            
            # 记录权益曲线
            self._record_equity(current_kline.timestamp, current_kline.close)
            
            # 进度显示
            if i % 500 == 0:
                progress = (i / total_bars) * 100
                logger.info(f"进度: {progress:.1f}% ({i}/{total_bars})")
        
        # 3. 强制平仓未平仓的持仓
        if self.current_position:
            last_kline = klines_5m[-1]
            closed_trade = self.simulator.execute_signal_close(
                self.current_position,
                last_kline.timestamp,
                last_kline.close
            )
            self.current_capital += closed_trade["pnl"]
            self.trades.append(closed_trade)
            logger.info("回测结束，强制平仓")
        
        logger.info("="*60)
        logger.info("回测完成！")
        logger.info("="*60)
        
        # 4. 生成结果
        return self._generate_result()
    
    def _build_market_snapshot(
        self,
        current_index: int,
        klines_5m: List,
        klines_15m: List,
        klines_1h: List
    ) -> MarketData:
        """构建当前时刻的市场数据快照"""
        current_kline = klines_5m[current_index]
        
        # 获取最近的K线数据
        recent_5m = klines_5m[max(0, current_index-120):current_index]
        recent_15m = self._get_recent_klines(klines_15m, current_kline.timestamp, 60)
        recent_1h = self._get_recent_klines(klines_1h, current_kline.timestamp, 30)
        
        # 计算技术指标
        indicators = self.ta_calculator.calculate_all_indicators(
            recent_5m, recent_15m, recent_1h
        )
        
        # 计算关键位
        key_levels_dict = self.ta_calculator.get_multi_period_levels(
            recent_5m, recent_15m, recent_1h, indicators
        )
        
        key_levels = KeyLevels(
            supports=key_levels_dict.get("supports", []),
            resistances=key_levels_dict.get("resistances", [])
        )
        
        # 构建持仓信息
        position = Position(
            has_position=self.current_position is not None,
            entry_price=self.current_position["entry_price"] if self.current_position else None,
            size_usdt=self.current_position["size_usdt"] if self.current_position else None,
            current_pnl_pct=None,
            entry_time=None
        )
        
        # 构建最新K线数据
        latest_klines = {
            "5m": [
                current_kline.timestamp,
                current_kline.open,
                current_kline.high,
                current_kline.low,
                current_kline.close,
                current_kline.volume
            ],
            "15m": self._kline_to_list(recent_15m[-1]) if recent_15m else [],
            "1h": self._kline_to_list(recent_1h[-1]) if recent_1h else []
        }
        
        return MarketData(
            symbol=self.symbol,
            current_price=current_kline.close,
            latest_klines=latest_klines,
            position=position,
            key_levels=key_levels,
            capital=self.current_capital,
            max_daily_risk_pct=settings.max_daily_risk_pct,
            indicators=indicators
        )
    
    def _get_recent_klines(self, klines: List, target_timestamp: int, limit: int) -> List:
        """获取指定时间戳之前的最近N根K线"""
        recent = [k for k in klines if k.timestamp <= target_timestamp]
        return recent[-limit:] if len(recent) > limit else recent
    
    def _kline_to_list(self, kline) -> List:
        """将K线对象转换为列表"""
        return [
            kline.timestamp,
            kline.open,
            kline.high,
            kline.low,
            kline.close,
            kline.volume
        ]
    
    def _record_equity(self, timestamp: int, current_price: float):
        """记录权益曲线"""
        # 计算当前总权益
        total_equity = self.current_capital
        
        if self.current_position:
            position_value = self.simulator.calculate_position_value(
                self.current_position, current_price
            )
            total_equity += position_value["position_value"]
        
        self.equity_curve.append({
            "timestamp": timestamp,
            "equity": total_equity,
            "cash": self.current_capital,
            "position_value": position_value["position_value"] if self.current_position else 0
        })
    
    def _generate_result(self) -> Dict:
        """生成回测结果"""
        return {
            "config": {
                "symbol": self.symbol,
                "start_date": self.start_date,
                "end_date": self.end_date,
                "initial_capital": self.initial_capital
            },
            "trades": self.trades,
            "equity_curve": self.equity_curve,
            "final_capital": self.current_capital,
            "total_pnl": self.current_capital - self.initial_capital,
            "total_pnl_pct": ((self.current_capital - self.initial_capital) / self.initial_capital) * 100
        }
    
    def _generate_empty_result(self) -> Dict:
        """生成空结果"""
        return {
            "config": {
                "symbol": self.symbol,
                "start_date": self.start_date,
                "end_date": self.end_date,
                "initial_capital": self.initial_capital
            },
            "trades": [],
            "equity_curve": [],
            "final_capital": self.initial_capital,
            "total_pnl": 0,
            "total_pnl_pct": 0
        }
