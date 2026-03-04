"""Main trading bot entry point"""

import sys
import time
import threading
from datetime import datetime, timedelta
from apscheduler.schedulers.blocking import BlockingScheduler
from loguru import logger
from typing import Optional

from src.config.settings import settings
from src.monitor.logger import setup_logger
from src.data.okx_client import OKXClient
from src.data.models import MarketData, KeyLevels, Position
from src.data.position_state import PositionStateManager
from src.data.redis_state import RedisStateManager
from src.ai.agent import AIAgent
from src.risk.manager import RiskManager
from src.notify.dingtalk import DingTalkNotifier
from src.indicators.ta_calculator import TACalculator
from src.data.symbol_pool_manager import SymbolPoolManager


class TradingBot:
    """AI交易机器人主控制器"""
    
    def __init__(self):
        setup_logger()
        
        self.okx_client = OKXClient()
        self.ai_agent = AIAgent()
        self.risk_manager = RiskManager()
        self.position_state_manager = PositionStateManager()
        
        # 多标的轮动状态
        self.locked_symbol: Optional[str] = None  # 当前锁定标的
        self.lock_start_cycle: int = 0  # 空仓锁定开始的周期数
        self.cycle_count: int = 0  # 总周期计数
        self.lock_timeout_cycles: int = getattr(settings, 'lock_timeout_cycles', 2)
        
        # Redis状态管理（先初始化，后续按标的切换）
        # 使用 symbol_pool 第一个标的初始化
        init_symbol = settings.symbol_pool.split(',')[0].strip() if settings.symbol_pool else "BTC-USDT"
        self.redis_state = RedisStateManager(init_symbol)
        
        # 动态标的池管理器（使用Redis存储，自动筛选更新）
        self.pool_manager = SymbolPoolManager(redis_client=self.redis_state.client)
        self._prev_atr_pct: float = 0  # 上次ATR%，用于紧急更新检测
        
        # 单标的模式：直接锁定（向后兼容）
        pool = self._get_symbol_pool()
        if len(pool) == 1:
            self.locked_symbol = pool[0]
        
        # Redis按标的隔离
        self.redis_state.switch_symbol(self.active_symbol)
        
        # 钉钉通知
        self.notifier = DingTalkNotifier(
            webhook_url=settings.dingtalk_webhook if settings.dingtalk_enabled else None,
            secret=settings.dingtalk_secret
        )
        
        # TA-Lib技术指标计算器
        self.ta_calculator = TACalculator()
        
        self.current_position: Position = Position(has_position=False)
        self.capital = settings.initial_capital
        
        # 订单跟踪（完全自己实现止损止盈，不用OKX条件单）
        self.stop_loss_price: Optional[float] = None
        self.take_profit_prices: list = []  # 止盈价格列表（单TP全仓出）
        self.tp_order_ids: list = []  # 预挂的TP限价卖单order_id列表
        self.position_size: Optional[float] = None  # 持仓数量（基础货币，如BTC/SENT/ETH）
        self.initial_position_size: Optional[float] = None  # 初始持仓数量
        
        # 价格监控线程控制
        self.price_monitor_running = False
        self.price_monitor_thread = None
        
        # 限价单失败冷却机制
        self.order_failed_cooling_until: Optional[float] = None  # 冷却结束时间戳
        
        # 调度器引用（用于平仓后立即触发下一轮）
        self.scheduler: Optional[BlockingScheduler] = None
        
        # 启动时恢复持仓状态（包括止损止盈）
        self._restore_position_state()
        
        # 当前交易ID（用于记录交易历史）
        self.current_trade_id: Optional[str] = None
        
        logger.info("=" * 60)
        logger.info("AI OKX Trader Started")
        pool = self._get_symbol_pool()
        if len(pool) > 1:
            logger.info(f"Symbol Pool: {pool} (多标的轮动模式)")
        else:
            logger.info(f"Symbol: {self.active_symbol} (单标的模式)")
        logger.info(f"Initial Capital: {self.capital} USDT")
        logger.info(f"Cycle Interval: {settings.cycle_interval_seconds}s")
        logger.info(f"Testnet: {settings.okx_testnet}")
        if not settings.okx_testnet:
            logger.info("⚠️ LIVE TRADING MODE")
        logger.info("=" * 60)
    
    @property
    def active_symbol(self) -> str:
        """当前活跃交易标的：锁定标的 > 池中第一个"""
        if self.locked_symbol:
            return self.locked_symbol
        pool = self._get_symbol_pool()
        return pool[0] if pool else "BTC-USDT"
    
    def _get_symbol_pool(self) -> list:
        """获取标的池列表（优先从动态池管理器读取，降级到settings.py）"""
        if hasattr(self, 'pool_manager'):
            pool = self.pool_manager.get_pool()
            if pool:
                return pool
        # 降级：从settings读取
        pool_str = getattr(settings, 'symbol_pool', '')
        if pool_str:
            return [s.strip() for s in pool_str.split(',') if s.strip()]
        # 如果 symbol_pool 也为空，返回默认值
        return ["BTC-USDT"]
    
    def _lock_symbol(self, symbol: str):
        """锁定标的，暂停其他标的分析"""
        self.locked_symbol = symbol
        self.lock_start_cycle = self.cycle_count
        self.redis_state.switch_symbol(symbol)
        logger.info(f"🔒 已锁定标的{symbol}，暂停其他标的分析，仅监控该标的")
    
    def _unlock_symbol(self):
        """解锁当前标的，恢复标的池筛选"""
        if not self.locked_symbol:
            return
        old_symbol = self.locked_symbol
        # 保存当前标的AI历史到Redis
        self.redis_state.save_ai_history(self.ai_agent.history, expire_hours=2)
        self.ai_agent.history = []
        # 重置锁定状态
        self.locked_symbol = None
        self.lock_start_cycle = 0
        logger.info(f"🔓 标的{old_symbol}平仓完成/空仓锁定超时，自动解锁，恢复标的池筛选")
    
    # ==================== 动态标的池管理 ====================
    
    def _refresh_symbol_pool_job(self):
        """定时任务：刷新标的池（每2小时执行）"""
        try:
            # 每日跨日检测
            self.pool_manager.daily_reset_if_needed()
            
            # 常规刷新
            updated = self.pool_manager.refresh_pool()
            if updated:
                new_pool = self.pool_manager.get_pool()
                logger.info(f"📊 标的池已自动更新: {new_pool[:10]}")
                
                # 检查当前锁定标的是否被剔除
                if self.locked_symbol and not self.pool_manager.is_valid_symbol(self.locked_symbol):
                    logger.warning(f"⚠️ 当前标的{self.locked_symbol}已从标的池剔除")
                    if self.current_position.has_position:
                        logger.warning(f"⚠️ 持仓中的标的被剔除，将在下个周期执行平仓切换")
                    else:
                        self._unlock_symbol()
        except Exception as e:
            logger.error(f"标的池刷新任务异常: {e}")
    
    def _validate_current_symbol(self) -> bool:
        """
        交易前校验当前标的是否仍在有效池内
        
        Returns:
            True=继续交易当前标的, False=需要切换
        """
        if not self.locked_symbol:
            return True  # 未锁定，扫描模式
        
        # 检查标的是否在池内
        if self.pool_manager.is_valid_symbol(self.locked_symbol):
            score = self.pool_manager.get_symbol_score(self.locked_symbol)
            if score is not None and score < 40:
                logger.warning(f"⚠️ {self.locked_symbol}评分{score:.1f}<40，需要切换")
                return False
            return True
        
        logger.warning(f"⚠️ {self.locked_symbol}不在当前标的池内")
        return False
    
    def _handle_symbol_removed(self):
        """当前标的被剔除时的处理：有仓则AI决策平仓，无仓则直接切换"""
        if self.current_position.has_position:
            logger.warning(f"🔄 {self.locked_symbol}已被剔除，持仓中，等待AI决策平仓")
            # 不强制立即平仓，让正常交易循环中AI来决策
            # AI会看到趋势信号自行判断，或在下个周期由紧急触发处理
        else:
            # 无持仓，直接切换到最优标的
            best = self.pool_manager.get_best_symbol(exclude=[self.locked_symbol])
            if best:
                logger.info(f"🔄 切换标的: {self.locked_symbol} → {best}")
                self._unlock_symbol()
            else:
                logger.warning("⚠️ 标的池为空，解锁等待下次筛选")
                self._unlock_symbol()
    
    def _check_emergency_pool_update(self, market_data=None):
        """检查是否需要紧急更新标的池"""
        if not self.locked_symbol or not market_data:
            return
        
        # 计算持仓时间
        holding_minutes = 0
        if self.current_position.has_position and self.current_position.entry_time:
            holding_minutes = (datetime.now() - self.current_position.entry_time).total_seconds() / 60
        
        # 当前ATR（从indicators中读取1H ATR）
        current_atr_pct = 0
        if market_data.indicators and market_data.current_price:
            atr_1h = market_data.indicators.get("1H", {}).get("atr", 0)
            if atr_1h:
                current_atr_pct = (atr_1h / market_data.current_price) * 100
        
        current_pnl = self.current_position.current_pnl_pct if self.current_position.current_pnl_pct else 0
        
        need_update, reason = self.pool_manager.check_emergency_update(
            current_symbol=self.locked_symbol,
            current_pnl_pct=current_pnl,
            holding_minutes=holding_minutes,
            current_atr_pct=current_atr_pct,
            prev_atr_pct=self._prev_atr_pct
        )
        
        # 记录ATR供下次比较
        if current_atr_pct > 0:
            self._prev_atr_pct = current_atr_pct
        
        if need_update:
            logger.warning(f"🚨 紧急更新标的池: {reason}")
            self.pool_manager.refresh_pool()
    
    def _check_daily_loss_limit(self, pnl_pct: float, already_recorded: bool = False):
        """
        检查日亏损限额，超限自动关闭交易开关
        
        Args:
            pnl_pct: 本次交易盈亏百分比
            already_recorded: 是否已由调用方记录到risk_manager（避免重复计入）
        """
        if not already_recorded:
            from src.data.models import AIDecision
            dummy_decision = AIDecision(d="close", r="auto_check")
            self.risk_manager.record_trade(dummy_decision, pnl_pct)
        
        summary = self.risk_manager.get_daily_summary()
        total_risk = summary.get("total_risk_used", 0)
        total_pnl = summary.get("total_pnl", 0)
        
        logger.info(f"📊 日内统计: 总交易={summary.get('total_trades', 0)}, 总盈亏={total_pnl:.2f}%, 累计风险={total_risk:.2f}%")
        
        # 检查是否超过日最大亏损限额（5%）
        max_daily_loss = 5.0
        if total_risk >= max_daily_loss:
            reason = f"日亏损达{total_risk:.2f}%，超过限额{max_daily_loss}%"
            logger.error(f"🚨 风控触发: {reason}")
            logger.error(f"🔴 自动关闭交易开关，需手动在Redis中设置 {self.redis_state.SWITCH_KEY}=on 恢复")
            self.redis_state.set_trading_switch(False, reason)
            
            # 发送通知
            self.notifier.notify_risk_rejected(
                symbol=self.active_symbol,
                action="auto_stop",
                reason=reason,
                risk_reason=f"累计亏损{total_risk:.2f}% >= {max_daily_loss}%"
            )
    
    def init_market_history(self):
        """
        初始化历史K线数据，为AI构建初始记忆
        仅在程序启动时执行一次
        """
        logger.info("\n" + "=" * 60)
        logger.info("开始加载历史K线数据...")
        
        try:
            # 1. 拉取3个周期的历史K线
            logger.info(f"正在获取 {self.active_symbol} 历史K线数据...")
            
            klines_5m = self.okx_client.get_klines(self.active_symbol, "5m", 120)
            klines_15m = self.okx_client.get_klines(self.active_symbol, "15m", 60)
            klines_1h = self.okx_client.get_klines(self.active_symbol, "1H", 30)
            
            # 2. 数据验证
            if not klines_5m or not klines_15m or not klines_1h:
                logger.error("历史K线数据获取失败，部分数据为空")
                return False
            
            logger.info(f"✓ 5m K线: {len(klines_5m)} 根")
            logger.info(f"✓ 15m K线: {len(klines_15m)} 根")
            logger.info(f"✓ 1h K线: {len(klines_1h)} 根")
            
            # 3. 数据处理：按时间升序排列（OKX返回的是降序）
            klines_5m.reverse()
            klines_15m.reverse()
            klines_1h.reverse()
            
            # 4. 构建历史上下文消息
            history_context = self._build_history_context(
                klines_5m, klines_15m, klines_1h
            )
            
            # 5. 添加到AI初始上下文（不会被截断）
            self.ai_agent.initial_klines_context = [
                {
                    "role": "user",
                    "content": history_context
                },
                {
                    "role": "assistant",
                    "content": '{"d":"wait","r":"已接收历史数据，等待实时信号"}'
                }
            ]
            
            # 6. 记录到对话日志文件
            self.ai_agent.log_initial_klines()
            
            logger.info("✓ 历史K线数据已加载到AI记忆")
            logger.info("\n📝 历史数据预览 (前300字符):")
            logger.info("-" * 60)
            logger.info(history_context[:300] + "...")
            logger.info("-" * 60)
            logger.info("=" * 60 + "\n")
            return True
            
        except Exception as e:
            logger.error(f"历史K线初始化失败: {e}", exc_info=True)
            return False
    
    def _price_monitor_loop(self):
        """
        价格监控线程：每秒检查价格，自动处理止损和止盈
        完全自己实现，不使用OKX条件单
        """
        logger.info("🔍 价格监控线程已启动 (自动止损止盈)")
        
        while self.price_monitor_running:
            try:
                # 无持仓时：静默休眠，不调用任何API
                if not self.current_position.has_position:
                    time.sleep(5)
                    continue
                
                # 有持仓时：获取价格并积极监控
                current_price = self.okx_client.get_current_price(self.active_symbol)
                if not current_price:
                    time.sleep(1)
                    continue
                
                if self.current_position.has_position:
                    # 🔧 热加载：有持仓但无SL时，每5秒从Redis检查外部脚本写入的SL/TP
                    if not self.stop_loss_price:
                        if not hasattr(self, '_redis_check_counter'):
                            self._redis_check_counter = 0
                        self._redis_check_counter += 1
                        if self._redis_check_counter % 5 == 0:
                            try:
                                saved = self.redis_state.load_position()
                                if saved:
                                    if saved.get("stop_loss_price"):
                                        self.stop_loss_price = saved["stop_loss_price"]
                                        logger.success(f"🛡️ 从Redis热加载止损: {self.stop_loss_price}")
                                    tp = saved.get("take_profit_prices")
                                    if tp and tp != [None] and (not self.take_profit_prices or self.take_profit_prices == [None]):
                                        self.take_profit_prices = tp
                                        logger.success(f"🎯 从Redis热加载止盈: {self.take_profit_prices}")
                                        # 热加载TP后，如果没有TP挂单，立即挂出
                                        if not self.tp_order_ids and self.position_size:
                                            self._place_tp_limit_orders()
                                    if not self.position_size and saved.get("size_btc"):
                                        self.position_size = saved["size_btc"]
                                        self.initial_position_size = self.position_size
                                    if saved.get("entry_price") and (not self.current_position.entry_price or self.current_position.entry_price == current_price):
                                        from src.data.models import Position
                                        entry = saved["entry_price"]
                                        pnl = ((current_price - entry) / entry) * 100
                                        self.current_position = Position(
                                            has_position=True, entry_price=entry,
                                            size_usdt=self.current_position.size_usdt, current_pnl_pct=pnl
                                        )
                            except Exception as e:
                                logger.debug(f"Redis热加载检查失败: {e}")
                    
                    # 有持仓时：1秒一次，显示完整信息
                    tp_display = ", ".join([str(tp) for tp in self.take_profit_prices]) if self.take_profit_prices else "None"
                    logger.info(f"💹 价格监控 | 当前: {current_price} | 止损: {self.stop_loss_price} | 止盈: [{tp_display}]")
                    
                    # 1. 检查止损（优先级最高）
                    if self.stop_loss_price and current_price <= self.stop_loss_price:
                        logger.warning(f"🛑 触发止损！当前价格 {current_price} <= 止损价格 {self.stop_loss_price}")
                        # 发送止损通知
                        entry_price = self.current_position.entry_price if self.current_position.entry_price else self.stop_loss_price
                        pnl_pct = ((current_price - entry_price) / entry_price) * 100 if entry_price else 0
                        self.notifier.notify_stop_loss(
                            symbol=self.active_symbol,
                            price=current_price,
                            entry_price=entry_price,
                            pnl_pct=pnl_pct
                        )
                        self._execute_stop_loss(current_price)
                        time.sleep(1)
                        continue
                    
                    # 2. 自动追踪止损：价格上涨时逐步提高SL锁住利润
                    if self.stop_loss_price and self.current_position.entry_price:
                        entry = self.current_position.entry_price
                        profit_pct = ((current_price - entry) / entry) * 100
                        
                        # 阶梯式追踪止损（仅向上移动，永不下调）
                        new_sl = self.stop_loss_price
                        if profit_pct >= 1.0:
                            # 浮盈≥1.0% → SL移至入场价+0.5%
                            new_sl = max(new_sl, entry * 1.005)
                        elif profit_pct >= 0.8:
                            # 浮盈≥0.8% → SL移至入场价+0.3%
                            new_sl = max(new_sl, entry * 1.003)
                        elif profit_pct >= 0.5:
                            # 浮盈≥0.5% → SL移至入场价（保本）
                            new_sl = max(new_sl, entry)
                        
                        if new_sl > self.stop_loss_price:
                            old_sl = self.stop_loss_price
                            self.stop_loss_price = new_sl
                            logger.success(f"📈 追踪止损上移: {old_sl:.6f} -> {new_sl:.6f} (浮盈{profit_pct:.2f}%)")
                            # 异步保存到Redis（不阻塞监控循环）
                            try:
                                self.redis_state.save_position(
                                    entry_price=entry,
                                    size_btc=self.position_size,
                                    stop_loss_price=self.stop_loss_price,
                                    take_profit_prices=self.take_profit_prices
                                )
                            except Exception:
                                pass
                    
                    # 3. 检查TP限价挂单是否成交（每3秒查一次，减少API调用）
                    if not hasattr(self, '_tp_check_counter'):
                        self._tp_check_counter = 0
                    self._tp_check_counter += 1
                    
                    if self._tp_check_counter % 3 == 0:
                        active_tp_orders = [oid for oid in self.tp_order_ids if oid] if self.tp_order_ids else []
                        if active_tp_orders:
                            # 有活跃的TP挂单，检查成交状态
                            self._check_tp_order_fills(current_price)
                        elif self.take_profit_prices and self.position_size:
                            # 🔴 安全网：有TP价格但无TP挂单（重启/切换标的后丢失），重新挂出
                            logger.warning(f"⚠️ 检测到TP价格{self.take_profit_prices}但无活跃TP挂单，重新挂出...")
                            self._place_tp_limit_orders()
                    
                    time.sleep(1)  # 有持仓时每秒检查
                
            except Exception as e:
                logger.error(f"价格监控线程错误: {e}")
                time.sleep(1)
        
        logger.info("🔍 价格监控线程已停止")
    
    def _execute_stop_loss(self, current_price: float):
        """执行止损：先撤销TP挂单，再市价卖出"""
        try:
            base_currency = self.active_symbol.split('-')[0]
            logger.info(f"正在执行止损 @ ~{current_price}")
            
            # 🔴 先撤销所有TP限价挂单，避免SL和TP同时成交
            self._cancel_all_tp_orders()
            
            # 使用close_position方法来查询实际持仓并平仓
            success = self.okx_client.close_position(self.active_symbol)
            
            if success:
                logger.success(f"✓ 止损单已执行")
                
                # 记录平仓交易和盈亏
                if self.current_trade_id and self.current_position.has_position:
                    pnl_usdt = (current_price - self.current_position.entry_price) * self.position_size
                    pnl_pct = (current_price - self.current_position.entry_price) / self.current_position.entry_price * 100
                    
                    self.redis_state.record_trade_close(
                        trade_id=self.current_trade_id,
                        exit_price=current_price,
                        close_reason="stop_loss",
                        pnl_usdt=pnl_usdt,
                        pnl_pct=pnl_pct
                    )
                    
                    # 🔴 检查日亏损限额
                    self._check_daily_loss_limit(pnl_pct)
                
                # 只有成功时才清空持仓状态
                self._clear_position_state()
            else:
                logger.error("❌ 止损单执行失败，保留持仓状态等待重试")
                # 失败时不清除状态，下次继续尝试
            
        except Exception as e:
            logger.error(f"执行止损失败: {e}，保留持仓状态等待重试")
    
    def _place_tp_limit_orders(self):
        """开仓成交后，预挂TP限价卖单到交易所（零滑点止盈，全仓一个TP）"""
        if not self.take_profit_prices or not self.position_size:
            return
        
        self.tp_order_ids = []
        
        # 只取第一个TP价格，全仓挂单
        tp_price = self.take_profit_prices[0]
        sell_size = self.position_size
        
        order_id = self.okx_client.place_limit_order(
            symbol=self.active_symbol,
            side="sell",
            price=tp_price,
            size=sell_size
        )
        
        if order_id:
            self.tp_order_ids.append(order_id)
            logger.success(f"✓ TP限价卖单已挂出: {sell_size:.8f} @ {tp_price}, ordId={order_id}")
        else:
            self.tp_order_ids.append(None)
            logger.error(f"❌ TP限价卖单挂出失败: {sell_size:.8f} @ {tp_price}")
    
    def _check_tp_order_fills(self, current_price: float):
        """检查预挂的TP限价卖单是否已在交易所成交（单TP全仓模式）"""
        if not self.tp_order_ids:
            return
        
        order_id = self.tp_order_ids[0] if self.tp_order_ids else None
        if not order_id:
            return
        
        try:
            order_status = self.okx_client.get_order_status(self.active_symbol, order_id)
            if not order_status:
                return
            
            if order_status['state'] == 'filled':
                fill_price = order_status['avgPx']
                fill_size = order_status['accFillSz']
                
                logger.success(f"🎯 TP限价卖单已成交! 成交价: {fill_price}, 数量: {fill_size}")
                
                # 发送止盈通知
                entry_price = self.current_position.entry_price if self.current_position.entry_price else fill_price
                pnl_pct = ((fill_price - entry_price) / entry_price) * 100 if entry_price else 0
                self.notifier.notify_take_profit(
                    symbol=self.active_symbol,
                    price=fill_price,
                    entry_price=entry_price,
                    pnl_pct=pnl_pct
                )
                
                # 记录平仓交易和盈亏
                if self.current_trade_id and self.current_position.has_position:
                    pnl_usdt = (fill_price - self.current_position.entry_price) * fill_size
                    total_pnl_pct = ((fill_price - self.current_position.entry_price) / self.current_position.entry_price) * 100
                    
                    self.redis_state.record_trade_close(
                        trade_id=self.current_trade_id,
                        exit_price=fill_price,
                        close_reason="tp",
                        pnl_usdt=pnl_usdt,
                        pnl_pct=total_pnl_pct
                    )
                    self._check_daily_loss_limit(total_pnl_pct)
                
                # 全仓已出，清除持仓状态
                self._clear_position_state()
                
        except Exception as e:
            logger.warning(f"检查TP订单状态失败: {e}")
    
    def _restore_position_state(self):
        """启动时恢复持仓状态（包括止损止盈）"""
        try:
            # 1. 从交易所获取实际持仓
            position = self.okx_client.get_position(self.active_symbol)
            
            if not position or not position.has_position:
                logger.info("📋 无持仓，无需恢复状态")
                return
            
            logger.warning(f"⚠️ 检测到持仓！入场价: {position.entry_price}, 数量: {position.size_usdt / position.entry_price:.8f}")
            
            # 2. 尝试从文件恢复止损止盈
            saved_state = self.position_state_manager.load_state()
            
            has_sl = saved_state and saved_state.get('stop_loss_price')
            has_tp = saved_state and (saved_state.get('take_profit_prices') or saved_state.get('take_profit_price'))
            if has_sl and has_tp:
                # 从文件恢复
                self.stop_loss_price = saved_state['stop_loss_price']
                # 兼容新旧格式
                if saved_state.get('take_profit_prices'):
                    self.take_profit_prices = saved_state['take_profit_prices']
                else:
                    tp_price = saved_state['take_profit_price']
                    self.take_profit_prices = [tp_price] if tp_price else []
                self.position_size = saved_state.get('size_btc', position.size_usdt / position.entry_price)
                self.initial_position_size = self.position_size
                
                logger.success(f"✓ 从文件恢复止损止盈: SL={self.stop_loss_price}, TP={self.take_profit_prices}")
            else:
                # 文件中没有止损止盈
                logger.error("=" * 60)
                logger.error("❌ 检测到持仓但无止损止盈信息！")
                logger.error("=" * 60)
                logger.error("请选择以下方式之一设置止损止盈：")
                logger.error("")
                logger.error("方式1：使用手动设置脚本（推荐）")
                logger.error("  python scripts/set_stop_loss.py")
                logger.error("")
                logger.error("方式2：让系统自动计算（基于1H ATR）")
                logger.error("  在 logs/position_state.json 中添加 \"auto_calculate\": true")
                logger.error("")
                logger.error("=" * 60)
                
                # 检查是否允许自动计算
                if saved_state and saved_state.get('auto_calculate'):
                    logger.warning("⚠️ 检测到auto_calculate标志，根据策略自动设置")
                
                # 获取1H ATR
                klines_1h = self.okx_client.get_klines(self.active_symbol, "1H", 30)
                if klines_1h:
                    df_1h = self.ta_calculator.calculate_indicators(klines_1h, "1H")
                    atr_1h = df_1h['atr'].iloc[-1]
                    
                    # 止损 = 入场价 - 0.5倍ATR
                    sl_distance = 0.5 * atr_1h
                    self.stop_loss_price = position.entry_price - sl_distance
                    
                    # 单止盈 = 入场价 + 1.5倍止损空间（盈亏比1:1.5）
                    tp = position.entry_price + 1.5 * sl_distance
                    self.take_profit_prices = [tp]
                    
                    self.position_size = position.size_usdt / position.entry_price
                    self.initial_position_size = self.position_size
                    
                    logger.warning(f"🛡️ 自动设置止损止盈: SL={self.stop_loss_price:.6f}, TP={tp:.6f}")
                    logger.warning(f"📊 基于1H ATR={atr_1h:.6f}, 止损空间={sl_distance:.6f}, 盈亏比1:1.5")
                    
                    # 保存到文件和Redis
                    self.position_state_manager.save_state(
                        symbol=self.active_symbol,
                        entry_price=position.entry_price,
                        size_btc=self.position_size,
                        stop_loss_price=self.stop_loss_price,
                        take_profit_prices=self.take_profit_prices
                    )
                    self.redis_state.save_position(
                        entry_price=position.entry_price,
                        size_btc=self.position_size,
                        stop_loss_price=self.stop_loss_price,
                        take_profit_prices=self.take_profit_prices
                    )
                else:
                    logger.error("❌ 无法获取1H K线数据，无法自动设置止损止盈")
                    logger.error("❌ 请手动平仓或设置止损止盈！")
                    return
            
            # 3. 更新持仓对象
            self.current_position = position
            
            # 4. 重新挂出TP限价卖单（重启后order_id丢失，需要重新挂单）
            if self.take_profit_prices and self.position_size:
                logger.info("📋 重启恢复：重新挂出TP限价卖单...")
                self._place_tp_limit_orders()
            
            # 5. 启动价格监控线程
            self._start_price_monitor()
            
            logger.success("✓ 持仓状态恢复完成，价格监控已启动")
            
        except Exception as e:
            logger.error(f"恢复持仓状态失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    def _cancel_all_tp_orders(self):
        """撤销所有预挂的TP限价卖单"""
        if not self.tp_order_ids:
            return
        for order_id in self.tp_order_ids:
            if order_id:
                try:
                    self.okx_client.cancel_order(self.active_symbol, order_id)
                    logger.info(f"✓ 已撤销TP挂单: {order_id}")
                except Exception as e:
                    logger.warning(f"撤销TP挂单失败({order_id}): {e}")
        self.tp_order_ids = []
    
    def _clear_position_state(self):
        """清空持仓状态（统一方法）"""
        # 先撤销所有TP挂单
        self._cancel_all_tp_orders()
        
        self.current_position = Position(has_position=False)
        self.stop_loss_price = None
        self.take_profit_prices = []
        self.tp_order_ids = []
        self.position_size = None
        self.initial_position_size = None
        self.current_trade_id = None
        
        # 同时清除文件和Redis状态
        self.position_state_manager.clear_state()
        self.redis_state.clear_position()
        logger.info("📋 本地持仓状态已清除（文件+Redis）")
        
        # 多标的模式：平仓后自动解锁，恢复标的池筛选
        if len(self._get_symbol_pool()) > 1 and self.locked_symbol:
            self._unlock_symbol()
        
        # 平仓后立即触发下一轮筛选
        self._trigger_immediate_cycle()
    
    def _get_current_interval(self) -> int:
        """根据持仓状态返回当前应使用的周期间隔（秒）"""
        if self.current_position.has_position:
            return settings.cycle_interval_seconds  # 有持仓：5min
        return getattr(settings, 'cycle_interval_no_position', 900)  # 无持仓：15min
    
    def _run_cycle_and_reschedule(self):
        """执行交易循环后，根据持仓状态动态调整下一轮间隔"""
        self.run_cycle()
        
        # 检查是否需要切换周期
        new_interval = self._get_current_interval()
        if hasattr(self, '_current_interval') and new_interval != self._current_interval:
            try:
                self.scheduler.reschedule_job(
                    'trading_cycle',
                    trigger='interval',
                    seconds=new_interval
                )
                old_interval = self._current_interval
                self._current_interval = new_interval
                logger.info(f"⏱️ 周期切换: {old_interval}s -> {new_interval}s ({'有持仓' if self.current_position.has_position else '无持仓'})")
            except Exception as e:
                logger.warning(f"动态调整周期失败: {e}")
    
    def _trigger_immediate_cycle(self):
        """平仓后立即触发下一轮交易循环，不等待定时器"""
        if self.scheduler:
            try:
                from datetime import timedelta
                run_time = datetime.now() + timedelta(seconds=5)
                self.scheduler.add_job(
                    self.run_cycle,
                    'date',
                    run_date=run_time,
                    id='immediate_cycle',
                    replace_existing=True
                )
                logger.info("🚀 平仓完成，5秒后立即开始下一轮标的筛选")
            except Exception as e:
                logger.warning(f"触发立即循环失败: {e}")
    
    def _start_price_monitor(self):
        """启动价格监控线程"""
        if not self.price_monitor_running:
            self.price_monitor_running = True
            self.price_monitor_thread = threading.Thread(
                target=self._price_monitor_loop,
                daemon=True
            )
            self.price_monitor_thread.start()
            logger.info("✓ 价格监控线程已启动")
    
    def _stop_price_monitor(self):
        """停止价格监控线程"""
        if self.price_monitor_running:
            self.price_monitor_running = False
            if self.price_monitor_thread:
                self.price_monitor_thread.join(timeout=2)
            logger.info("✓ 价格监控线程已停止")
    
    def _build_history_context(self, klines_5m, klines_15m, klines_1h) -> str:
        """
        构建历史K线上下文消息
        
        Args:
            klines_5m: 5分钟K线列表
            klines_15m: 15分钟K线列表
            klines_1h: 1小时K线列表
        
        Returns:
            格式化的历史数据字符串
        """
        # 格式化K线数据为简洁字符串
        def format_klines(klines):
            """格式化K线数据为简洁字符串（完整数据）"""
            return [
                f"[{k.timestamp}, O:{k.open:.1f}, H:{k.high:.1f}, L:{k.low:.1f}, C:{k.close:.1f}, V:{k.volume:.0f}]"
                for k in klines
            ]
        
        context = f"""【历史K线数据初始化】

交易对: {self.active_symbol}
数据时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

=== 5分钟K线 (共{len(klines_5m)}根) ===
{chr(10).join(format_klines(klines_5m))}

=== 15分钟K线 (共{len(klines_15m)}根) ===
{chr(10).join(format_klines(klines_15m))}

=== 1小时K线 (共{len(klines_1h)}根) ===
{chr(10).join(format_klines(klines_1h))}

当前价格: {klines_5m[-1].close:.2f}

请基于以上历史数据建立市场认知，等待后续实时数据进行交易决策。"""
        
        return context
    
    def _quick_check_symbol(self, symbol: str) -> bool:
        """
        轻量级技术预筛选（不调用AI），检查1H趋势和15m量能
        仅通过基础指标快速排除明显不适合的标的，节省AI调用成本
        
        Returns:
            True=通过预筛选，值得让AI深入分析
        """
        try:
            # 获取1H K线（只需最近30根）
            klines_1h = self.okx_client.get_klines(symbol, "1H", 30)
            if not klines_1h or len(klines_1h) < 20:
                return False
            
            # 获取15m K线（只需最近20根）
            klines_15m = self.okx_client.get_klines(symbol, "15m", 20)
            if not klines_15m or len(klines_15m) < 10:
                return False
            
            # 1H趋势检查：价格不能低于MA20太多（排除明确下跌趋势）
            closes_1h = [k.close for k in klines_1h]
            ma20 = sum(closes_1h[-20:]) / 20 if len(closes_1h) >= 20 else None
            current_price = closes_1h[-1]
            
            if ma20 and current_price < ma20 * 0.97:
                logger.debug(f"  ✗ {symbol} 价格低于1H MA20 3%+，趋势偏空，跳过")
                return False
            
            # 15m量能检查：最近3根15m成交量不能太低
            recent_vols = [k.volume for k in klines_15m[-3:]]
            avg_vol = sum([k.volume for k in klines_15m[-10:]]) / 10
            recent_avg = sum(recent_vols) / 3
            
            if avg_vol > 0 and recent_avg / avg_vol < 0.3:
                logger.debug(f"  ✗ {symbol} 15m近期量能过低(相对值={recent_avg/avg_vol:.2f})，跳过")
                return False
            
            return True
            
        except Exception as e:
            logger.debug(f"  ✗ {symbol} 预筛选异常: {e}")
            return False
    
    def _scan_symbol_pool(self):
        """扫描标的池，寻找满足开仓条件的标的（含技术预筛选）"""
        pool = self._get_symbol_pool()
        
        if not pool:
            logger.warning("⚠️ 标的池为空，暂停交易，等待下次筛选更新")
            self.locked_symbol = None
            return
        
        logger.info(f"🔍 标的池筛选开始，共{len(pool)}个标的: {pool}")
        
        # 第1轮：轻量级技术预筛选（不调用AI，节省成本）
        candidates = []
        for symbol in pool:
            if self._quick_check_symbol(symbol):
                candidates.append(symbol)
            else:
                logger.info(f"  ⏭️ {symbol} 未通过技术预筛选，跳过AI分析")
        
        if not candidates:
            self.locked_symbol = None
            self.ai_agent.history = []
            logger.info(f"� 预筛选完毕：{len(pool)}个标的全部不满足基础条件，继续观望")
            return
        
        logger.info(f"📊 预筛选通过{len(candidates)}/{len(pool)}个标的，开始AI深度分析: {candidates}")
        
        # 第2轮：AI深度分析（仅对预筛选通过的标的）
        for symbol in candidates:
            logger.info(f"�� 正在AI分析标的: {symbol}")
            
            # 临时切换到当前标的进行分析
            self.locked_symbol = symbol
            self.redis_state.switch_symbol(symbol)
            
            # 加载该标的的AI历史
            self.ai_agent.history = []
            redis_history = self.redis_state.load_ai_history()
            if redis_history:
                self.ai_agent.history = redis_history
            
            # 收集市场数据
            market_data = self._collect_market_data()
            if not market_data:
                logger.warning(f"❌ {symbol} 数据获取失败，跳过")
                continue
            
            # AI决策
            decision = self.ai_agent.make_decision(market_data)
            logger.info(f"📋 {symbol} AI决策: {decision.d} - {decision.r}")
            
            # 保存该标的的AI历史
            self.redis_state.save_ai_history(self.ai_agent.history, expire_hours=2)
            
            if decision.d == "long":
                # 正式锁定该标的
                self.lock_start_cycle = self.cycle_count
                logger.info(f"🔒 标的池筛选：{symbol}满足开仓条件，锁定为当前交易标的")
                
                # 风控验证
                passed, risk_reason = self.risk_manager.validate_decision(decision, market_data)
                if not passed:
                    logger.warning(f"Decision rejected by risk manager: {risk_reason}")
                    if decision.d in ["long", "close"]:
                        self.notifier.notify_risk_rejected(
                            symbol=symbol,
                            action=decision.d,
                            reason=decision.r,
                            risk_reason=risk_reason
                        )
                    return
                
                # 执行开仓
                self._execute_decision(decision, market_data)
                
                summary = self.risk_manager.get_daily_summary()
                logger.info(f"Daily Summary: {summary}")
                return
        
        # 无标的满足条件，清除临时锁定
        self.locked_symbol = None
        self.ai_agent.history = []
        logger.info(f"🔍 标的池筛选完毕，AI分析{len(candidates)}个标的均无开仓信号，继续观望")
    
    def run_cycle(self):
        """执行一次交易循环"""
        try:
            # 🔴 检查Redis交易开关
            if not self.redis_state.is_trading_enabled():
                reason = self.redis_state.get_switch_reason()
                logger.warning(f"⏸️ 交易已暂停 | 原因: {reason or '手动关闭'} | Redis key: {self.redis_state.SWITCH_KEY}=off | 设置为on以恢复交易")
                return
            
            self.cycle_count += 1
            logger.info(f"\n{'='*60}")
            logger.info(f"Cycle #{self.cycle_count} started at {datetime.now()}")
            
            # 动态标的池校验：检查当前标的是否仍有效
            if self.locked_symbol and not self._validate_current_symbol():
                self._handle_symbol_removed()
                if self.locked_symbol is None:
                    # 已切换/解锁，进入扫描模式
                    self._scan_symbol_pool()
                    logger.info(f"Cycle #{self.cycle_count} completed at {datetime.now()}")
                    logger.info("=" * 60)
                    return
            
            # 多标的轮动：未锁定时进入扫描模式
            if self.locked_symbol is None:
                self._scan_symbol_pool()
                logger.info(f"Cycle #{self.cycle_count} completed at {datetime.now()}")
                logger.info("=" * 60)
                return
            
            # 锁定模式：检查空仓锁定超时
            if not self.current_position.has_position and len(self._get_symbol_pool()) > 1:
                cycles_locked = self.cycle_count - self.lock_start_cycle
                if cycles_locked >= self.lock_timeout_cycles:
                    logger.info(f"⏰ 标的{self.locked_symbol}空仓锁定超时({cycles_locked}周期≥{self.lock_timeout_cycles})，自动解锁，重新筛选标的池")
                    self._unlock_symbol()
                    logger.info(f"Cycle #{self.cycle_count} completed at {datetime.now()}")
                    logger.info("=" * 60)
                    return
            
            logger.info(f"🔒 当前锁定标的: {self.active_symbol}")
            
            # 正常交易循环（原有逻辑）
            market_data = self._collect_market_data()
            
            if not market_data:
                logger.error("Failed to collect market data, skipping cycle")
                return
            
            logger.info(f"Current price: {market_data.current_price}")
            logger.info(f"Position: {market_data.position}")
            
            # 🔧 检测未保护的仓位（手动开仓或重启后丢失SL/TP）
            if market_data.position.has_position and not self.stop_loss_price:
                logger.warning("⚠️ 检测到未保护仓位（无止损），将让AI立即补设止损止盈")
                # 同步仓位信息到本地
                if market_data.position.entry_price:
                    self.current_position = market_data.position
                    if not self.position_size and market_data.position.size_usdt and market_data.position.entry_price:
                        self.position_size = market_data.position.size_usdt / market_data.position.entry_price
                        self.initial_position_size = self.position_size
                    logger.info(f"📋 同步仓位: 入场价={market_data.position.entry_price}, 浮动盈亏={market_data.position.current_pnl_pct}%")
            
            # 紧急标的池更新检测（浮亏/波动率突变/评分下跌）
            self._check_emergency_pool_update(market_data)
            
            decision = self.ai_agent.make_decision(market_data)
            logger.info(f"AI Decision: {decision.d} - {decision.r}")
            
            # 风控验证
            passed, risk_reason = self.risk_manager.validate_decision(decision, market_data)
            if not passed:
                logger.warning(f"Decision rejected by risk manager: {risk_reason}")
                
                # 发送风控拦截通知
                if decision.d in ["long", "close"]:
                    self.notifier.notify_risk_rejected(
                        symbol=self.active_symbol,
                        action=decision.d,
                        reason=decision.r,
                        risk_reason=risk_reason
                    )
                return
            
            self._execute_decision(decision, market_data)
            
            summary = self.risk_manager.get_daily_summary()
            logger.info(f"Daily Summary: {summary}")
            
            logger.info(f"Cycle #{self.cycle_count} completed at {datetime.now()}")
            logger.info("=" * 60)
            
        except Exception as e:
            logger.error(f"Error in trading cycle: {e}", exc_info=True)
    
    def _collect_market_data(self) -> MarketData:
        """收集市场数据"""
        try:
            current_price = self.okx_client.get_current_price(self.active_symbol)
            if not current_price:
                return None
            
            klines_5m = self.okx_client.get_klines(self.active_symbol, "5m", 120)
            klines_15m = self.okx_client.get_klines(self.active_symbol, "15m", 60)
            klines_1h = self.okx_client.get_klines(self.active_symbol, "1H", 30)
            
            if not klines_5m or not klines_15m or not klines_1h:
                logger.error("Failed to fetch klines")
                return None
            
            # 计算技术指标
            indicators = self.ta_calculator.calculate_all_indicators(
                klines_5m, klines_15m, klines_1h
            )
            logger.debug(f"技术指标已计算: {len(indicators)} 个时间周期")
            
            latest_klines = {
                "5m": [klines_5m[0].timestamp, klines_5m[0].open, klines_5m[0].high, 
                       klines_5m[0].low, klines_5m[0].close, klines_5m[0].volume],
                "15m": [klines_15m[0].timestamp, klines_15m[0].open, klines_15m[0].high,
                        klines_15m[0].low, klines_15m[0].close, klines_15m[0].volume],
                "1h": [klines_1h[0].timestamp, klines_1h[0].open, klines_1h[0].high,
                       klines_1h[0].low, klines_1h[0].close, klines_1h[0].volume]
            }
            
            # 获取持仓状态
            okx_position = self.okx_client.get_position(self.active_symbol)
            
            # 现货模式：如果检测到持仓，从Redis恢复真实入场价和SL/TP
            if settings.trading_mode == "cash" and okx_position.has_position:
                saved_state = self.redis_state.load_position()
                if saved_state and saved_state.get("entry_price"):
                    # 使用保存的入场价替换临时价格
                    real_entry_price = saved_state.get("entry_price")
                    pnl_pct = ((current_price - real_entry_price) / real_entry_price) * 100
                    
                    okx_position = Position(
                        has_position=True,
                        entry_price=real_entry_price,
                        size_usdt=okx_position.size_usdt,
                        current_pnl_pct=pnl_pct
                    )
                    logger.info(f"✓ 从Redis恢复入场价: {real_entry_price}, 当前盈亏: {pnl_pct:.2f}%")
                    
                    # 🔧 从Redis同步SL/TP（支持外部脚本set_stop_loss.py写入）
                    if not self.stop_loss_price and saved_state.get("stop_loss_price"):
                        self.stop_loss_price = saved_state["stop_loss_price"]
                        logger.success(f"🛡️ 从Redis恢复止损: {self.stop_loss_price}")
                    if not self.take_profit_prices or self.take_profit_prices == [None]:
                        tp = saved_state.get("take_profit_prices")
                        if tp and tp != [None]:
                            self.take_profit_prices = tp
                            logger.success(f"🎯 从Redis恢复止盈: {self.take_profit_prices}")
                            # 恢复TP后，如果没有TP挂单，立即挂出
                            if not self.tp_order_ids and self.position_size:
                                self._place_tp_limit_orders()
                    if not self.position_size and saved_state.get("size_btc"):
                        self.position_size = saved_state["size_btc"]
                        self.initial_position_size = self.position_size
                        logger.info(f"📋 从Redis恢复持仓数量: {self.position_size}")
                else:
                    logger.warning("⚠️ 检测到现货持仓但无入场价记录，无法计算准确盈亏")
            
            # 如果OKX显示无持仓，但我们有保存的止损止盈价格，说明可能刚平仓
            # 此时应该清除保存的状态
            if not okx_position.has_position and (self.stop_loss_price or self.take_profit_prices):
                logger.warning("⚠️ OKX显示无持仓，但本地有止损止盈记录，可能已被平仓，清除本地状态")
                # 撤销可能残留的TP挂单
                self._cancel_all_tp_orders()
                self.stop_loss_price = None
                self.take_profit_prices = []
                self.tp_order_ids = []
                self.position_size = None
                self.initial_position_size = None
                self.position_state_manager.clear_state()
                self.redis_state.clear_position()
            
            # 统一使用okx_position作为position
            position = okx_position
            self.current_position = position
            
            # 使用TA-Lib计算器计算多周期关键位
            key_levels_dict = self.ta_calculator.get_multi_period_levels(
                klines_5m, klines_15m, klines_1h, indicators
            )
            
            # 转换为KeyLevels对象
            key_levels = KeyLevels(
                supports=key_levels_dict.get("supports", []),
                resistances=key_levels_dict.get("resistances", [])
            )
            
            balance = self.okx_client.get_balance("USDT")
            if balance > 0:
                self.capital = balance
            
            return MarketData(
                symbol=self.active_symbol,
                current_price=current_price,
                latest_klines=latest_klines,
                position=position,
                key_levels=key_levels,
                capital=self.capital,
                max_daily_risk_pct=settings.max_daily_risk_pct,
                indicators=indicators
            )
            
        except Exception as e:
            logger.error(f"Error collecting market data: {e}")
            return None
    
    def _calculate_key_levels(self, klines: list) -> KeyLevels:
        """计算关键支撑/压力位"""
        if not klines or len(klines) < 10:
            return KeyLevels()
        
        highs = sorted([k.high for k in klines[-20:]], reverse=True)
        lows = sorted([k.low for k in klines[-20:]])
        
        resistances = highs[:2]
        supports = lows[:2]
        
        return KeyLevels(supports=supports, resistances=resistances)
    
    def _execute_decision(self, decision, market_data: MarketData):
        """执行交易决策"""
        try:
            if decision.d == "wait":
                logger.info("Decision: WAIT - No action taken")
                
                # 即使是wait决策，如果有持仓且AI提供了新的止损止盈价格，也要更新
                if self.current_position.has_position and (decision.sl or decision.tp):
                    sl_updated = False
                    tp_updated = False
                    
                    # 更新止损价格（增加安全间距校验）
                    if decision.sl and decision.sl != self.stop_loss_price:
                        # 首次设置止损（未保护仓位）：跳过间距校验
                        if self.stop_loss_price is None:
                            self.stop_loss_price = decision.sl
                            logger.success(f"🛡️ [WAIT决策] 首次设置止损: {self.stop_loss_price} (未保护仓位已获得止损保护)")
                            sl_updated = True
                        else:
                            # 获取5分钟ATR用于安全间距计算
                            atr_5m = market_data.indicators.get("5m", {}).get("atr", 0)
                            current_price = market_data.current_price
                            
                            # 计算止损与当前价格的间距
                            sl_distance = current_price - decision.sl
                            sl_distance_pct = (sl_distance / current_price) * 100
                            
                            # 安全间距要求：≥0.5倍5分钟ATR，且至少0.3%
                            min_distance_atr = 0.5 * atr_5m if atr_5m > 0 else 0
                            min_distance_pct = 0.3
                            
                            # 校验止损间距
                            if sl_distance < min_distance_atr or sl_distance_pct < min_distance_pct:
                                logger.warning(
                                    f"⚠️ 止损间距不足，拒绝更新！"
                                    f"当前价格={current_price}, 建议止损={decision.sl}, "
                                    f"间距={sl_distance:.4f}({sl_distance_pct:.2f}%), "
                                    f"要求≥{min_distance_atr:.4f}(0.5*ATR) 且 ≥{min_distance_pct}%"
                                )
                            else:
                                # 校验通过，允许更新
                                old_sl = self.stop_loss_price
                                self.stop_loss_price = decision.sl
                                logger.success(
                                    f"🔄 [WAIT决策] 止损价格已更新: {old_sl} -> {self.stop_loss_price} "
                                    f"(间距={sl_distance:.4f}/{sl_distance_pct:.2f}%, ATR={atr_5m:.4f})"
                                )
                                sl_updated = True
                    
                    # 更新止盈价格（支持多个止盈位）
                    if decision.tp and len(decision.tp) > 0:
                        if decision.tp != self.take_profit_prices:
                            old_tp = self.take_profit_prices.copy()
                            # 撤销旧的TP限价卖单
                            self._cancel_all_tp_orders()
                            self.take_profit_prices = decision.tp.copy()
                            # 重新挂出新的TP限价卖单
                            self._place_tp_limit_orders()
                            logger.success(f"🔄 [WAIT决策] 止盈价格已更新: {old_tp} -> {self.take_profit_prices}, TP挂单已重新挂出")
                            tp_updated = True
                    
                    # 如果有更新,保存到Redis和文件
                    if sl_updated or tp_updated:
                        self.redis_state.save_position(
                            entry_price=self.current_position.entry_price,
                            size_btc=self.position_size,
                            stop_loss_price=self.stop_loss_price,
                            take_profit_prices=self.take_profit_prices
                        )
                        self.position_state_manager.save_state(
                            symbol=self.active_symbol,
                            entry_price=self.current_position.entry_price,
                            size_btc=self.position_size,
                            stop_loss_price=self.stop_loss_price,
                            take_profit_prices=self.take_profit_prices
                        )
                        logger.info(f"💾 持仓状态已更新: 止损={self.stop_loss_price}, 止盈={self.take_profit_prices}")
                
                return
            
            if decision.d == "close":
                if self.current_position.has_position:
                    logger.info("Executing CLOSE position")
                    # 先撤销TP挂单，释放冻结余额
                    self._cancel_all_tp_orders()
                    success = self.okx_client.close_position(self.active_symbol)
                    
                    if success:
                        pnl = self.current_position.current_pnl_pct if self.current_position.current_pnl_pct else 0
                        self.risk_manager.record_trade(decision, pnl)
                        logger.success(f"Position closed, PnL: {pnl:.2f}%")
                        
                        # 发送平仓执行成功通知（使用 notify_position_closed）
                        self.notifier.notify_position_closed(
                            symbol=self.active_symbol,
                            entry_price=self.current_position.entry_price,
                            exit_price=market_data.current_price,
                            pnl_pct=pnl,
                            reason=decision.r
                        )
                        
                        # 🔴 检查日亏损限额（record_trade已调用，标记already_recorded）
                        self._check_daily_loss_limit(pnl, already_recorded=True)
                        
                        # 清理持仓状态,防止价格监控线程继续触发止损
                        self._clear_position_state()
                else:
                    logger.warning("No position to close")
            
            elif decision.d == "long":
                # 检查是否在冷却期
                if self.order_failed_cooling_until:
                    import time
                    current_time = time.time()
                    if current_time < self.order_failed_cooling_until:
                        remaining_seconds = int(self.order_failed_cooling_until - current_time)
                        logger.warning(f"🚫 限价单失败冷却中，剩余{remaining_seconds}秒，拒绝开仓信号")
                        return
                    else:
                        # 冷却期结束
                        logger.info("✓ 冷却期结束，恢复接收开仓信号")
                        self.order_failed_cooling_until = None
                
                if self.current_position.has_position:
                    # 已有持仓,检查是否需要调整止损止盈
                    sl_updated = False
                    tp_updated = False
                    
                    # 更新止损价格（增加安全间距校验）
                    if decision.sl and decision.sl != self.stop_loss_price:
                        # 首次设置止损（未保护仓位）：跳过间距校验，任何SL都比没有好
                        if self.stop_loss_price is None:
                            self.stop_loss_price = decision.sl
                            logger.success(f"🛡️ 首次设置止损: {self.stop_loss_price} (未保护仓位已获得止损保护)")
                            sl_updated = True
                        else:
                            # 获取5分钟ATR用于安全间距计算
                            atr_5m = market_data.indicators.get("5m", {}).get("atr", 0)
                            current_price = market_data.current_price
                            
                            # 计算止损与当前价格的间距
                            sl_distance = current_price - decision.sl
                            sl_distance_pct = (sl_distance / current_price) * 100
                            
                            # 安全间距要求：从配置读取
                            min_distance_atr = settings.trailing_stop_atr_multiplier * atr_5m if atr_5m > 0 else 0
                            min_distance_pct = settings.trailing_stop_min_distance_pct
                            
                            # 校验止损间距
                            if sl_distance < min_distance_atr or sl_distance_pct < min_distance_pct:
                                logger.warning(
                                    f"⚠️ 止损间距不足，拒绝更新！"
                                    f"当前价格={current_price}, 建议止损={decision.sl}, "
                                    f"间距={sl_distance:.4f}({sl_distance_pct:.2f}%), "
                                    f"要求≥{min_distance_atr:.4f}({settings.trailing_stop_atr_multiplier}*ATR) 且 ≥{min_distance_pct}%"
                                )
                            else:
                                # 校验通过，允许更新
                                old_sl = self.stop_loss_price
                                self.stop_loss_price = decision.sl
                                logger.success(
                                    f"🔄 [LONG决策] 止损价格已更新: {old_sl} -> {self.stop_loss_price} "
                                    f"(间距={sl_distance:.4f}/{sl_distance_pct:.2f}%, ATR={atr_5m:.4f})"
                                )
                                sl_updated = True
                    
                    # 更新止盈价格（支持多个止盈位）
                    if decision.tp and len(decision.tp) > 0:
                        if decision.tp != self.take_profit_prices:
                            old_tp = self.take_profit_prices.copy()
                            # 撤销旧的TP限价卖单
                            self._cancel_all_tp_orders()
                            self.take_profit_prices = decision.tp.copy()
                            # 重新挂出新的TP限价卖单
                            self._place_tp_limit_orders()
                            logger.success(f"🔄 止盈价格已更新: {old_tp} -> {self.take_profit_prices}, TP挂单已重新挂出")
                            tp_updated = True
                    
                    # 如果有更新,保存到Redis和文件
                    if sl_updated or tp_updated:
                        self.redis_state.save_position(
                            entry_price=self.current_position.entry_price,
                            size_btc=self.position_size,
                            stop_loss_price=self.stop_loss_price,
                            take_profit_prices=self.take_profit_prices
                        )
                        self.position_state_manager.save_state(
                            symbol=self.active_symbol,
                            entry_price=self.current_position.entry_price,
                            size_btc=self.position_size,
                            stop_loss_price=self.stop_loss_price,
                            take_profit_prices=self.take_profit_prices
                        )
                        logger.info(f"💾 持仓状态已更新: 止损={self.stop_loss_price}, 止盈={self.take_profit_prices}")
                    else:
                        logger.info("Already have position, no SL/TP changes needed")
                    
                    return
                
                # 解析入场价格（支持区间格式）
                entry_min, entry_max = decision.get_entry_price_range()
                if entry_min is None or entry_max is None:
                    logger.error(f"无效的入场价格格式: {decision.e}")
                    return
                
                # 使用区间中间价作为限价单价格
                entry_price = (entry_min + entry_max) / 2
                logger.info(f"Executing LONG: size={decision.s}%, entry_range={decision.e}, limit_price={entry_price:.4f}, sl={decision.sl}, tp={decision.tp}")
                
                size_usdt = self.capital * (decision.s / 100)
                size_btc = size_usdt / entry_price  # 使用计算的入场价
                
                # 使用限价单,价格为区间中间价
                order_id = self.okx_client.place_limit_order(
                    symbol=self.active_symbol,
                    side="buy",
                    price=entry_price,  # 使用区间中间价
                    size=size_btc  # 使用基础货币数量
                )
                
                if not order_id:
                    logger.error("Failed to place LONG limit order")
                    return
                
                logger.success(f"✓ LONG限价单已提交: {order_id} @ {entry_price:.6f}")
                logger.info(f"💡 限价单等待成交,价格: {entry_price:.6f}, 数量: {size_btc:.8f}")
                
                # 从配置读取超时参数
                timeout = getattr(settings, 'limit_order_timeout', 90)
                logger.info(f"💡 限价单超时时间: {timeout}秒，超时未成交将撤单并进入冷却期")
                
                # 等待限价单成交（设置超时）
                import time
                wait_interval = 5  # 每5秒检查一次
                max_checks = timeout // wait_interval  # 最多检查次数
                check_count = 0
                order_filled = False
                
                while check_count < max_checks:
                    time.sleep(wait_interval)
                    check_count += 1
                    elapsed_time = check_count * wait_interval
                    
                    order_status = self.okx_client.get_order_status(self.active_symbol, order_id)
                    if not order_status:
                        logger.warning(f"无法查询订单状态,继续等待... (已等待{elapsed_time}s/{timeout}s)")
                        continue
                    
                    if order_status['state'] == 'filled':
                        actual_entry_price = order_status['avgPx']
                        actual_fill_size = order_status['accFillSz']
                        logger.success(f"✓ 限价单已成交! 成交价: {actual_entry_price}, 数量: {actual_fill_size}")
                        order_filled = True
                        
                        # 发送交易执行成功通知
                        self.notifier.notify_trade_executed(
                            symbol=self.active_symbol,
                            action="long",
                            price=float(actual_entry_price),
                            size=decision.s,
                            reason=decision.r,
                            stop_loss=decision.sl,
                            take_profit=decision.tp
                        )
                        break
                    elif order_status['state'] == 'canceled':
                        logger.error("限价单已被撤销")
                        return
                    elif order_status['state'] == 'live':
                        logger.info(f"订单挂单中... (已等待{elapsed_time}s/{timeout}s)")
                    else:
                        logger.info(f"订单状态: {order_status['state']}, 继续等待... (已等待{elapsed_time}s/{timeout}s)")
                
                # 超时未成交，撤单并进入冷却
                if not order_filled:
                    logger.warning(f"⏰ 限价单在{timeout}秒内未成交，准备撤单")
                    cancel_success = self.okx_client.cancel_order(self.active_symbol, order_id)
                    
                    if cancel_success:
                        logger.warning(f"✓ 限价单已撤销: {order_id}")
                    else:
                        logger.error(f"❌ 撤单失败，请手动检查订单状态")
                    
                    # 进入冷却期
                    cooling_minutes = getattr(settings, 'order_failed_cooling', 3)
                    self.order_failed_cooling_until = time.time() + (cooling_minutes * 60)
                    logger.warning(f"🚫 限价单超时未成交，撤单并冷却{cooling_minutes}分钟（行情不配合，放弃本次开仓）")
                    logger.warning(f"💡 冷却期间将拒绝所有开仓信号，避免频繁无效挂单")
                    return
                
                # 记录仓位信息和止损止盈价格（使用实际成交价）
                self.position_size = actual_fill_size  # 实际成交数量
                self.initial_position_size = actual_fill_size  # 记录初始数量
                self.current_position = Position(
                    has_position=True,
                    entry_price=actual_entry_price,
                    size_usdt=actual_entry_price * actual_fill_size
                )
                
                # 止损：价格监控线程每秒检查，触发后市价卖出
                # 止盈：预挂限价卖单到交易所，零滑点成交
                
                # 设置止损价格（由价格监控线程自动执行）
                if decision.sl:
                    # 🔴 硬性校验：初始止损间距不能过小，防止秒触发止损送手续费
                    sl_distance_pct = (actual_entry_price - decision.sl) / actual_entry_price * 100
                    min_sl_pct = settings.initial_sl_min_distance_pct  # 默认0.3%
                    if sl_distance_pct < min_sl_pct:
                        old_sl = decision.sl
                        decision.sl = actual_entry_price * (1 - min_sl_pct / 100)
                        logger.warning(
                            f"⚠️ AI止损间距过小({sl_distance_pct:.3f}% < {min_sl_pct}%)，"
                            f"自动拓宽: {old_sl} -> {decision.sl:.6f} (间距={min_sl_pct}%)"
                        )
                    self.stop_loss_price = decision.sl
                    final_sl_pct = (actual_entry_price - self.stop_loss_price) / actual_entry_price * 100
                    logger.success(f"✓ 止损价格已设置: {self.stop_loss_price} (间距={final_sl_pct:.3f}%, 价格监控自动执行)")
                else:
                    logger.warning("⚠️ No stop loss set - 风险较高！")
                
                # 设置止盈价格并预挂限价卖单
                if decision.tp and len(decision.tp) > 0:
                    self.take_profit_prices = decision.tp.copy()
                    logger.success(f"✓ 止盈价格: {self.take_profit_prices}")
                    # 预挂TP限价卖单到交易所（核心改进：零滑点止盈）
                    self._place_tp_limit_orders()
                
                logger.info("📋 订单组: 限价入场 + 自动止损监控 + TP限价卖单(预挂)")
                logger.info(f"💡 止损由价格监控线程执行，止盈由交易所限价单自动成交")
                logger.info(f"📝 持仓记录: 入场价={actual_entry_price}, 数量={size_btc}, 止损={self.stop_loss_price}, 止盈={self.take_profit_prices}, TP挂单={self.tp_order_ids}")
                
                # 保存持仓状态到文件和Redis（完整止盈列表）
                self.position_state_manager.save_state(
                    symbol=self.active_symbol,
                    entry_price=actual_entry_price,
                    size_btc=size_btc,
                    stop_loss_price=self.stop_loss_price,
                    take_profit_prices=self.take_profit_prices
                )
                self.redis_state.save_position(
                    entry_price=actual_entry_price,
                    size_btc=size_btc,
                    stop_loss_price=self.stop_loss_price,
                    take_profit_prices=self.take_profit_prices
                )
                
                # 记录交易开仓
                self.current_trade_id = self.redis_state.record_trade_open(
                    entry_price=actual_entry_price,
                    size_usdt=size_usdt,
                    stop_loss=self.stop_loss_price,
                    take_profit=self.take_profit_prices
                )
                logger.info(f"📊 交易记录ID: {self.current_trade_id}")
        
        except Exception as e:
            logger.error(f"Error executing decision: {e}")
    
    def start(self):
        """启动交易机器人"""
        try:
            # 🔧 多标的模式：启动时检测标的池中是否有已持仓标的，自动锁定
            pool = self._get_symbol_pool()
            if len(pool) > 1:
                for symbol in pool:
                    position = self.okx_client.get_position(symbol)
                    if position and position.has_position:
                        self._lock_symbol(symbol)
                        logger.info(f"🔒 启动时检测到{symbol}持仓，自动锁定")
                        break
            
            # 🔧 加载AI历史记录（从Redis，按标的隔离）
            redis_history = self.redis_state.load_ai_history()
            if redis_history:
                self.ai_agent.history = redis_history
                logger.success(f"✓ 从Redis加载AI历史: {len(redis_history)} 条消息 (标的: {self.active_symbol})")
            else:
                logger.info(f"无历史记录，从头开始 (标的: {self.active_symbol})")
            
            # 🔧 加载持仓状态（从Redis）
            saved_state = self.redis_state.load_position()
            
            if saved_state:
                logger.info("检测到持仓状态，正在恢复...")
                self.stop_loss_price = saved_state.get("stop_loss_price")
                # 兼容新旧格式：新格式take_profit_prices(列表)，旧格式take_profit_price(单值)
                if saved_state.get("take_profit_prices"):
                    self.take_profit_prices = saved_state["take_profit_prices"]
                else:
                    saved_tp = saved_state.get("take_profit_price")
                    self.take_profit_prices = [saved_tp] if saved_tp else []
                self.position_size = saved_state.get("size_btc")  # 兼容旧字段名
                self.initial_position_size = self.position_size  # 恢复初始数量
                logger.success(f"✓ 已恢复持仓状态: 止损={self.stop_loss_price}, 止盈={self.take_profit_prices}")
            else:
                logger.info("无持仓状态")
            
            # 🔧 技术指标计算器已就绪，无需单独加载历史K线
            logger.info("✓ AI交易系统已启动，技术指标将在每次决策时实时计算")
            
            # 启动价格监控线程
            self._start_price_monitor()
            
            # 🔧 启动时初始化标的池（如果启用了自动筛选）
            if settings.enable_auto_screening:
                if not self.pool_manager.get_pool() or self.pool_manager.seconds_since_last_update() > 7200:
                    logger.info("📊 启动时初始化标的池...")
                    self.pool_manager.refresh_pool(force=True)
                else:
                    last = self.pool_manager.get_last_update_time()
                    pool = self.pool_manager.get_pool()
                    logger.info(f"📊 标的池已存在: {pool[:5]}... (上次更新: {last.strftime('%H:%M') if last else 'N/A'})")
            else:
                logger.info("⚠️ 自动筛选已禁用，使用 SYMBOL_POOL 配置")
            
            # 执行首次循环
            logger.info("Running initial cycle...")
            self.run_cycle()
            
            self.scheduler = BlockingScheduler()
            
            # 动态周期：有持仓5min，无持仓15min
            initial_interval = self._get_current_interval()
            self.scheduler.add_job(
                self._run_cycle_and_reschedule,
                'interval',
                seconds=initial_interval,
                id='trading_cycle'
            )
            self._current_interval = initial_interval
            
            # 标的池定时刷新（每2小时，仅当启用自动筛选时）
            if settings.enable_auto_screening:
                self.scheduler.add_job(
                    self._refresh_symbol_pool_job,
                    'interval',
                    seconds=7200,
                    id='pool_refresh',
                    next_run_time=datetime.now() + timedelta(seconds=7200)
                )
                logger.info("📊 标的池自动刷新已启用（每2小时）")
            else:
                logger.info("⚠️ 标的池自动刷新已禁用，使用静态 SYMBOL_POOL 配置")
            
            logger.info(f"Scheduler started, interval={initial_interval}s (动态: 有持仓{settings.cycle_interval_seconds}s, 无持仓{settings.cycle_interval_no_position}s)")
            self.scheduler.start()
            
        except KeyboardInterrupt:
            logger.info("Received keyboard interrupt, shutting down...")
            self._shutdown()
        except Exception as e:
            logger.error(f"Fatal error: {e}", exc_info=True)
            self._shutdown()
    
    def _shutdown(self):
        """关闭机器人"""
        logger.info("Shutting down...")
        
        # 停止价格监控线程
        self._stop_price_monitor()
        
        # 保存AI历史到Redis（按标的隔离，2小时过期）
        logger.info(f"Saving AI history to Redis (标的: {self.active_symbol})...")
        self.redis_state.save_ai_history(self.ai_agent.history, expire_hours=2)
        
        summary = self.risk_manager.get_daily_summary()
        logger.info(f"Final Summary: {summary}")
        
        logger.info("AI OKX Trader stopped")
        sys.exit(0)


def main():
    """主入口"""
    bot = TradingBot()
    bot.start()


if __name__ == "__main__":
    main()
