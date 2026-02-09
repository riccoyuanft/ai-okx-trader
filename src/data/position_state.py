"""持仓状态持久化"""

import json
import os
from typing import Optional
from loguru import logger


class PositionStateManager:
    """管理持仓状态的持久化"""
    
    def __init__(self, filepath: str = "logs/position_state.json"):
        self.filepath = filepath
        self._ensure_dir()
    
    def _ensure_dir(self):
        """确保目录存在"""
        os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
    
    def save_state(self, 
                   symbol: str,
                   entry_price: float,
                   size_btc: float,
                   stop_loss_price: Optional[float],
                   take_profit_prices: Optional[list] = None):
        """保存持仓状态"""
        try:
            state = {
                "symbol": symbol,
                "entry_price": entry_price,
                "size_btc": size_btc,
                "stop_loss_price": stop_loss_price,
                "take_profit_prices": take_profit_prices or []
            }
            
            with open(self.filepath, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
            
            logger.info(f"持仓状态已保存到 {self.filepath}")
        except Exception as e:
            logger.error(f"保存持仓状态失败: {e}")
    
    def load_state(self) -> Optional[dict]:
        """加载持仓状态"""
        try:
            if not os.path.exists(self.filepath):
                return None
            
            with open(self.filepath, 'r', encoding='utf-8') as f:
                state = json.load(f)
            
            logger.info(f"持仓状态已从 {self.filepath} 加载")
            return state
        except Exception as e:
            logger.error(f"加载持仓状态失败: {e}")
            return None
    
    def clear_state(self):
        """清除持仓状态"""
        try:
            if os.path.exists(self.filepath):
                os.remove(self.filepath)
                logger.info(f"持仓状态已清除")
        except Exception as e:
            logger.error(f"清除持仓状态失败: {e}")
