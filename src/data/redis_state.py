"""Redis持仓状态和AI历史管理（同步版本）"""

import json
import redis
from typing import Optional, List, Dict
from datetime import datetime
from loguru import logger
from src.config.settings import settings


class RedisStateManager:
    """Redis状态管理器（同步版本，适配现有代码）"""
    
    def __init__(self, symbol: str):
        """
        初始化Redis状态管理器
        
        Args:
            symbol: 交易对，如 BTC-USDT
        """
        self.symbol = symbol
        self.client: Optional[redis.Redis] = None
        self._connect()
    
    def _connect(self):
        """创建Redis连接"""
        if not settings.use_redis:
            logger.warning("Redis未启用，状态将不会持久化到Redis")
            return
        
        try:
            self.client = redis.Redis(
                host=settings.redis_host,
                port=settings.redis_port,
                db=settings.redis_db,
                password=settings.redis_password,
                decode_responses=True
            )
            self.client.ping()
            logger.info(f"Redis连接成功 ({settings.redis_host}:{settings.redis_port}/{settings.redis_db})")
        except Exception as e:
            logger.error(f"Redis连接失败: {e}")
            self.client = None
    
    def _get_key(self, key_type: str) -> str:
        """生成Redis键名"""
        return f"ai_trader:{self.symbol}:{key_type}"
    
    # ==================== 持仓状态管理 ====================
    
    def save_position(self, 
                      entry_price: float,
                      size_btc: float,
                      stop_loss_price: Optional[float],
                      take_profit_prices: Optional[List[float]] = None):
        """
        保存持仓状态到Redis
        
        持仓状态不设过期时间，持有仓位期间需要一直保留
        """
        if not self.client:
            return
        
        try:
            key = self._get_key("position")
            state = {
                "symbol": self.symbol,
                "entry_price": str(entry_price),
                "size_btc": str(size_btc),
                "stop_loss_price": str(stop_loss_price) if stop_loss_price else "",
                "take_profit_prices": json.dumps(take_profit_prices) if take_profit_prices else "[]"
            }
            self.client.hset(key, mapping=state)
            logger.info(f"持仓状态已保存到Redis: {key}")
        except Exception as e:
            logger.error(f"保存持仓状态到Redis失败: {e}")
    
    def load_position(self) -> Optional[dict]:
        """从Redis加载持仓状态"""
        if not self.client:
            return None
        
        try:
            key = self._get_key("position")
            state = self.client.hgetall(key)
            
            if not state:
                return None
            
            # 转换类型
            result = {
                "symbol": state.get("symbol", self.symbol),
                "entry_price": float(state["entry_price"]) if state.get("entry_price") else None,
                "size_btc": float(state["size_btc"]) if state.get("size_btc") else None,
                "stop_loss_price": float(state["stop_loss_price"]) if state.get("stop_loss_price") else None,
            }
            # 兼容新旧格式：新格式take_profit_prices(JSON列表)，旧格式take_profit_price(单值)
            if state.get("take_profit_prices"):
                result["take_profit_prices"] = json.loads(state["take_profit_prices"])
            elif state.get("take_profit_price"):
                result["take_profit_prices"] = [float(state["take_profit_price"])]
            else:
                result["take_profit_prices"] = []
            
            logger.info(f"从Redis加载持仓状态: {result}")
            return result
        except Exception as e:
            logger.error(f"从Redis加载持仓状态失败: {e}")
            return None
    
    def clear_position(self):
        """清除持仓状态"""
        if not self.client:
            return
        
        try:
            key = self._get_key("position")
            self.client.delete(key)
            logger.info(f"Redis持仓状态已清除: {key}")
        except Exception as e:
            logger.error(f"清除Redis持仓状态失败: {e}")
    
    # ==================== AI历史管理 ====================
    
    def save_ai_history(self, history: List[Dict], expire_hours: int = 24):
        """
        保存AI历史到Redis
        
        Args:
            history: AI对话历史
            expire_hours: 过期时间（小时），默认24小时
                         - 设置过期时间是因为历史记录有时效性
                         - 过久的历史对当前决策帮助有限
        """
        if not self.client:
            return
        
        try:
            key = self._get_key("ai_history")
            self.client.set(key, json.dumps(history, ensure_ascii=False))
            self.client.expire(key, expire_hours * 3600)
            logger.info(f"AI历史已保存到Redis: {key} (过期时间: {expire_hours}小时)")
        except Exception as e:
            logger.error(f"保存AI历史到Redis失败: {e}")
    
    def load_ai_history(self) -> List[Dict]:
        """从Redis加载AI历史"""
        if not self.client:
            return []
        
        try:
            key = self._get_key("ai_history")
            data = self.client.get(key)
            
            if not data:
                logger.info(f"Redis中无AI历史: {key}")
                return []
            
            history = json.loads(data)
            logger.info(f"从Redis加载AI历史: {len(history)} 条消息")
            return history
        except Exception as e:
            logger.error(f"从Redis加载AI历史失败: {e}")
            return []
    
    def clear_ai_history(self):
        """清除AI历史"""
        if not self.client:
            return
        
        try:
            key = self._get_key("ai_history")
            self.client.delete(key)
            logger.info(f"Redis AI历史已清除: {key}")
        except Exception as e:
            logger.error(f"清除Redis AI历史失败: {e}")
    
    # ==================== 交易开关（全局） ====================
    
    SWITCH_KEY = "ai_trader:trading_switch"
    SWITCH_REASON_KEY = "ai_trader:trading_switch_reason"
    
    def is_trading_enabled(self) -> bool:
        """检查交易开关是否开启（默认开启）"""
        if not self.client:
            return True  # Redis不可用时默认开启
        
        try:
            val = self.client.get(self.SWITCH_KEY)
            if val is None:
                # 首次运行，初始化为开启
                self.client.set(self.SWITCH_KEY, "on")
                return True
            return val.lower() == "on"
        except Exception as e:
            logger.error(f"读取交易开关失败: {e}")
            return True  # 异常时默认开启
    
    def set_trading_switch(self, enabled: bool, reason: str = ""):
        """设置交易开关"""
        if not self.client:
            return
        
        try:
            self.client.set(self.SWITCH_KEY, "on" if enabled else "off")
            if reason:
                self.client.set(self.SWITCH_REASON_KEY, reason)
            status = "开启" if enabled else "关闭"
            logger.warning(f"🔴 交易开关已{status}: {reason}")
        except Exception as e:
            logger.error(f"设置交易开关失败: {e}")
    
    def get_switch_reason(self) -> str:
        """获取开关关闭原因"""
        if not self.client:
            return ""
        try:
            return self.client.get(self.SWITCH_REASON_KEY) or ""
        except:
            return ""
    
    # ==================== 标的切换支持 ====================
    
    def switch_symbol(self, new_symbol: str):
        """
        切换交易对
        
        注意：切换后会使用新标的的数据，旧标的数据保留在Redis中
        """
        old_symbol = self.symbol
        self.symbol = new_symbol
        logger.info(f"交易对已切换: {old_symbol} -> {new_symbol}")
    
    def get_all_symbols_with_position(self) -> List[str]:
        """获取所有有持仓状态的标的"""
        if not self.client:
            return []
        
        try:
            keys = self.client.keys("ai_trader:*:position")
            symbols = []
            for key in keys:
                # 从 ai_trader:BTC-USDT:position 提取 BTC-USDT
                parts = key.split(":")
                if len(parts) >= 2:
                    symbols.append(parts[1])
            return symbols
        except Exception as e:
            logger.error(f"获取持仓标的列表失败: {e}")
            return []
    
    # ==================== 交易记录管理 ====================
    
    def record_trade_open(self, entry_price: float, size_usdt: float, stop_loss: float, take_profit: List[float]) -> str:
        """
        记录开仓
        
        Args:
            entry_price: 入场价格
            size_usdt: 仓位大小(USDT)
            stop_loss: 止损价格
            take_profit: 止盈价格列表
            
        Returns:
            交易ID
        """
        if not self.client:
            return ""
        
        try:
            trade_id = f"{self.symbol}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            key = self._get_key(f"trade:{trade_id}")
            
            trade_record = {
                "trade_id": trade_id,
                "symbol": self.symbol,
                "action": "open",
                "entry_price": str(entry_price),
                "size_usdt": str(size_usdt),
                "stop_loss": str(stop_loss),
                "take_profit": json.dumps([str(tp) for tp in take_profit]),
                "open_time": datetime.now().isoformat(),
                "status": "open"
            }
            
            self.client.hset(key, mapping=trade_record)
            
            # 添加到交易列表
            list_key = self._get_key("trade_list")
            self.client.lpush(list_key, trade_id)
            
            logger.info(f"✓ 开仓记录已保存: {trade_id}")
            return trade_id
        except Exception as e:
            logger.error(f"记录开仓失败: {e}")
            return ""
    
    def record_trade_close(self, trade_id: str, exit_price: float, close_reason: str, pnl_usdt: float, pnl_pct: float):
        """
        记录平仓
        
        Args:
            trade_id: 交易ID
            exit_price: 出场价格
            close_reason: 平仓原因 (stop_loss/tp1/tp2/manual)
            pnl_usdt: 盈亏金额(USDT)
            pnl_pct: 盈亏百分比
        """
        if not self.client:
            return
        
        try:
            key = self._get_key(f"trade:{trade_id}")
            
            if not self.client.exists(key):
                logger.warning(f"交易记录不存在: {trade_id}")
                return
            
            update_data = {
                "exit_price": str(exit_price),
                "close_reason": close_reason,
                "pnl_usdt": str(pnl_usdt),
                "pnl_pct": str(pnl_pct),
                "close_time": datetime.now().isoformat(),
                "status": "closed"
            }
            
            self.client.hset(key, mapping=update_data)
            logger.info(f"✓ 平仓记录已保存: {trade_id}, PnL: {pnl_usdt:.2f} USDT ({pnl_pct:.2f}%)")
        except Exception as e:
            logger.error(f"记录平仓失败: {e}")
    
    def get_trade_history(self, limit: int = 50) -> List[Dict]:
        """
        获取交易历史
        
        Args:
            limit: 返回记录数量限制
            
        Returns:
            交易记录列表
        """
        if not self.client:
            return []
        
        try:
            list_key = self._get_key("trade_list")
            trade_ids = self.client.lrange(list_key, 0, limit - 1)
            
            trades = []
            for trade_id in trade_ids:
                key = self._get_key(f"trade:{trade_id}")
                trade_data = self.client.hgetall(key)
                
                if trade_data:
                    # 转换数据类型
                    trade = {
                        "trade_id": trade_data.get("trade_id"),
                        "symbol": trade_data.get("symbol"),
                        "action": trade_data.get("action"),
                        "entry_price": float(trade_data.get("entry_price", 0)),
                        "exit_price": float(trade_data.get("exit_price", 0)) if trade_data.get("exit_price") else None,
                        "size_usdt": float(trade_data.get("size_usdt", 0)),
                        "stop_loss": float(trade_data.get("stop_loss", 0)),
                        "take_profit": json.loads(trade_data.get("take_profit", "[]")),
                        "open_time": trade_data.get("open_time"),
                        "close_time": trade_data.get("close_time"),
                        "close_reason": trade_data.get("close_reason"),
                        "pnl_usdt": float(trade_data.get("pnl_usdt", 0)) if trade_data.get("pnl_usdt") else None,
                        "pnl_pct": float(trade_data.get("pnl_pct", 0)) if trade_data.get("pnl_pct") else None,
                        "status": trade_data.get("status")
                    }
                    trades.append(trade)
            
            return trades
        except Exception as e:
            logger.error(f"获取交易历史失败: {e}")
            return []
    
    def get_trade_statistics(self) -> Dict:
        """
        计算交易统计数据
        
        Returns:
            统计数据字典
        """
        if not self.client:
            return {}
        
        try:
            trades = self.get_trade_history(limit=1000)
            closed_trades = [t for t in trades if t["status"] == "closed"]
            
            if not closed_trades:
                return {
                    "total_trades": 0,
                    "win_trades": 0,
                    "loss_trades": 0,
                    "win_rate": 0.0,
                    "total_pnl_usdt": 0.0,
                    "avg_pnl_usdt": 0.0,
                    "max_win_usdt": 0.0,
                    "max_loss_usdt": 0.0
                }
            
            win_trades = [t for t in closed_trades if t["pnl_usdt"] and t["pnl_usdt"] > 0]
            loss_trades = [t for t in closed_trades if t["pnl_usdt"] and t["pnl_usdt"] <= 0]
            
            total_pnl = sum(t["pnl_usdt"] for t in closed_trades if t["pnl_usdt"])
            
            stats = {
                "total_trades": len(closed_trades),
                "win_trades": len(win_trades),
                "loss_trades": len(loss_trades),
                "win_rate": len(win_trades) / len(closed_trades) * 100 if closed_trades else 0.0,
                "total_pnl_usdt": total_pnl,
                "avg_pnl_usdt": total_pnl / len(closed_trades) if closed_trades else 0.0,
                "max_win_usdt": max([t["pnl_usdt"] for t in win_trades]) if win_trades else 0.0,
                "max_loss_usdt": min([t["pnl_usdt"] for t in loss_trades]) if loss_trades else 0.0
            }
            
            return stats
        except Exception as e:
            logger.error(f"计算交易统计失败: {e}")
            return {}
