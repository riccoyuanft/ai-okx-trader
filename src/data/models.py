"""Data models for market data and trading decisions"""

from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Literal, Union
from datetime import datetime


class KLine(BaseModel):
    """K线数据模型"""
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float


class Position(BaseModel):
    """持仓信息模型"""
    has_position: bool
    entry_price: Optional[float] = None
    size_usdt: Optional[float] = None
    current_pnl_pct: Optional[float] = None
    entry_time: Optional[datetime] = None


class KeyLevels(BaseModel):
    """关键价位模型"""
    supports: List[float] = Field(default_factory=list)
    resistances: List[float] = Field(default_factory=list)


class MarketData(BaseModel):
    """市场数据输入模型"""
    symbol: str
    current_price: float
    latest_klines: dict[str, List[float]]
    position: Position
    key_levels: KeyLevels
    capital: float
    max_daily_risk_pct: float
    indicators: Optional[dict] = None


class AIDecision(BaseModel):
    """AI决策输出模型"""
    d: Literal["long", "close", "wait"]
    s: Optional[int] = None
    e: Optional[Union[float, str]] = None  # 支持单一价格或区间格式 "3.405-3.412"
    sl: Optional[float] = None
    tp: Optional[List[float]] = None
    r: str
    trend_strength: Optional[str] = None  # 趋势强度（AI自由描述）
    is_chase_high: Optional[bool] = None  # 是否追高场景
    tp_strategy: Optional[str] = None  # 止盈策略（AI自由描述）
    
    @field_validator('e')
    @classmethod
    def validate_entry_price(cls, v):
        """验证并解析入场价格（支持区间格式）"""
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            # 保持字符串格式，后续在执行时解析
            return v
        return v
    
    @field_validator('tp')
    @classmethod
    def validate_take_profit(cls, v):
        """验证止盈位数量不超过2个"""
        if v is not None and len(v) > 2:
            # 只保留前2个止盈位
            return v[:2]
        return v
    
    def get_entry_price_range(self) -> tuple[Optional[float], Optional[float]]:
        """获取入场价格区间（返回min, max）"""
        if self.e is None:
            return None, None
        if isinstance(self.e, (int, float)):
            return float(self.e), float(self.e)
        if isinstance(self.e, str) and '-' in self.e:
            try:
                parts = self.e.split('-')
                min_price = float(parts[0].strip())
                max_price = float(parts[1].strip())
                return min_price, max_price
            except:
                return None, None
        return None, None
