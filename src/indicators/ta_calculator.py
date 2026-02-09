"""
TA-Lib技术指标计算工具类
独立模块，接收OKX原生K线数据，计算常用技术指标
"""

import numpy as np
import pandas as pd
from typing import List, Dict, Optional
from loguru import logger

from src.data.models import KLine
from src.config.settings import settings

try:
    import pandas_ta as ta
    TALIB_AVAILABLE = True
except ImportError:
    TALIB_AVAILABLE = False
    logger.warning("pandas-ta未安装，技术指标计算功能将不可用")


class TACalculator:
    """技术指标计算器"""
    
    def __init__(self):
        """初始化计算器"""
        logger.info("TA-Lib指标计算器已初始化")
    
    def calculate_all_indicators(
        self,
        klines_5m: List[KLine],
        klines_15m: List[KLine],
        klines_1h: List[KLine]
    ) -> Dict[str, Dict[str, float]]:
        """
        计算所有时间周期的技术指标
        
        Args:
            klines_5m: 5分钟K线列表
            klines_15m: 15分钟K线列表
            klines_1h: 1小时K线列表
        
        Returns:
            包含所有指标的字典，格式：
            {
                "5m": {"ma5": 4750.0, "ma10": 4745.0, ...},
                "15m": {...},
                "1h": {...}
            }
        """
        if not TALIB_AVAILABLE:
            logger.debug("TA-Lib不可用，跳过指标计算")
            return {"5m": {}, "15m": {}, "1h": {}}
        
        try:
            indicators = {
                "5m": self._calculate_indicators(klines_5m, "5m"),
                "15m": self._calculate_indicators(klines_15m, "15m"),
                "1h": self._calculate_indicators(klines_1h, "1H")
            }
            
            logger.debug("技术指标计算完成")
            return indicators
            
        except Exception as e:
            logger.error(f"技术指标计算失败: {e}")
            return {
                "5m": {},
                "15m": {},
                "1h": {}
            }
    
    def _calculate_indicators(self, klines: List[KLine], timeframe: str) -> Dict[str, float]:
        """
        计算单个时间周期的技术指标（仅返回最新值）
        
        Args:
            klines: K线列表
            timeframe: 时间周期（"5m", "15m", "1H"）
        
        Returns:
            最新K线的指标值字典
        """
        if not klines or len(klines) < 2:
            return {}
        
        # 构建DataFrame
        df = pd.DataFrame({
            'close': [k.close for k in klines],
            'high': [k.high for k in klines],
            'low': [k.low for k in klines],
            'volume': [k.volume for k in klines]
        })
        
        indicators = {}
        
        # 1. 移动平均线 (MA)
        if len(df) >= 5:
            ma5 = ta.sma(df['close'], length=5)
            indicators["ma5"] = self._safe_value(ma5.iloc[-1])
            # 增加MA5历史值（用于判断"向上"趋势）
            if timeframe == "15m" and len(df) >= 6:
                indicators["ma5_prev1"] = self._safe_value(ma5.iloc[-2])
        
        if len(df) >= 10:
            ma10 = ta.sma(df['close'], length=10)
            indicators["ma10"] = self._safe_value(ma10.iloc[-1])
        
        if len(df) >= 20:
            ma20 = ta.sma(df['close'], length=20)
            indicators["ma20"] = self._safe_value(ma20.iloc[-1])
            # 增加MA20历史值（用于判断"向上"趋势）
            if timeframe == "1H" and len(df) >= 22:
                indicators["ma20_prev1"] = self._safe_value(ma20.iloc[-2])
                indicators["ma20_prev2"] = self._safe_value(ma20.iloc[-3])
        
        if len(df) >= 60:
            ma60 = ta.sma(df['close'], length=60)
            indicators["ma60"] = self._safe_value(ma60.iloc[-1])
        
        # 2. 指数移动平均线 (EMA)
        if len(df) >= 12:
            ema12 = ta.ema(df['close'], length=12)
            indicators["ema12"] = self._safe_value(ema12.iloc[-1])
        
        if len(df) >= 26:
            ema26 = ta.ema(df['close'], length=26)
            indicators["ema26"] = self._safe_value(ema26.iloc[-1])
        
        # 3. MACD
        if len(df) >= 26:
            macd_df = ta.macd(df['close'], fast=12, slow=26, signal=9)
            if macd_df is not None and not macd_df.empty:
                indicators["macd"] = self._safe_value(macd_df.iloc[-1, 0])
                indicators["macd_hist"] = self._safe_value(macd_df.iloc[-1, 1])
                indicators["macd_signal"] = self._safe_value(macd_df.iloc[-1, 2])
        
        # 4. RSI
        if len(df) >= 14:
            rsi = ta.rsi(df['close'], length=14)
            indicators["rsi"] = self._safe_value(rsi.iloc[-1])
        
        # 5. 布林带 (BOLL)
        if len(df) >= 20:
            bbands = ta.bbands(df['close'], length=20, std=2)
            if bbands is not None and not bbands.empty:
                indicators["boll_lower"] = self._safe_value(bbands.iloc[-1, 0])
                indicators["boll_middle"] = self._safe_value(bbands.iloc[-1, 1])
                indicators["boll_upper"] = self._safe_value(bbands.iloc[-1, 2])
        
        # 6. ATR (平均真实波幅)
        if len(df) >= 14:
            atr = ta.atr(df['high'], df['low'], df['close'], length=14)
            indicators["atr"] = self._safe_value(atr.iloc[-1])
        
        # 7. 当前价格（用于对比）
        indicators["close"] = self._safe_value(df['close'].iloc[-1])
        
        # 8. 量能指标（VOL20均量、量能相对值、量能状态）
        vol_ma_period = getattr(settings, 'vol_ma_period', 20)
        vol_break_threshold = getattr(settings, 'vol_break_threshold', 1.5)
        vol_retrace_threshold = getattr(settings, 'vol_retrace_threshold', 1.0)
        
        current_volume = self._safe_value(df['volume'].iloc[-1])
        indicators["volume"] = current_volume
        
        if len(df) >= vol_ma_period:
            vol20 = ta.sma(df['volume'], length=vol_ma_period)
            vol20_val = self._safe_value(vol20.iloc[-1])
            indicators["vol20"] = vol20_val
            
            # 量能相对值 = 当前成交量 / VOL20
            if vol20_val and vol20_val > 0 and current_volume is not None:
                vol_ratio = round(current_volume / vol20_val, 2)
                indicators["vol_ratio"] = vol_ratio
                
                # 量能状态判定
                if vol_ratio > vol_break_threshold:
                    indicators["vol_status"] = "放量"
                elif vol_ratio < vol_retrace_threshold:
                    indicators["vol_status"] = "缩量"
                else:
                    indicators["vol_status"] = "正常"
                
                logger.debug(f"量能指标: volume={current_volume}, vol20={vol20_val}, ratio={vol_ratio}, status={indicators['vol_status']}")
        
        return indicators
    
    def _safe_value(self, value) -> Optional[float]:
        """
        安全处理指标值，处理NaN情况
        
        Args:
            value: 原始值（可能是float、numpy类型或pandas类型）
        
        Returns:
            处理后的值（保留4位小数），NaN返回None
        """
        try:
            # 转换为float
            val = float(value)
            # 检查是否为NaN
            if pd.isna(val) or np.isnan(val):
                return None
            return round(val, 4)
        except (ValueError, TypeError):
            return None
    
    def calc_support_resistance(
        self,
        klines: List[KLine],
        indicators: Dict[str, float]
    ) -> Dict[str, List[float]]:
        """
        计算单周期的支撑位和压力位
        
        计算规则：
        - 强支撑：布林带下轨、近期最低价
        - 弱支撑：MA20、MA60均线
        - 强压力：布林带上轨、近期最高价
        - 弱压力：MA20、MA60均线
        
        Args:
            klines: K线列表
            indicators: 该周期已计算的指标字典
        
        Returns:
            {"support": [点位1, 点位2], "resistance": [点位1, 点位2]}
        """
        if not klines or len(klines) < 10:
            return {"support": [], "resistance": []}
        
        support_levels = []
        resistance_levels = []
        
        try:
            highs = [k.high for k in klines]
            lows = [k.low for k in klines]
            
            if indicators.get("boll_lower") is not None:
                support_levels.append(("strong", indicators["boll_lower"]))
            
            recent_low = min(lows[-20:]) if len(lows) >= 20 else min(lows)
            support_levels.append(("strong", recent_low))
            
            if indicators.get("ma20") is not None:
                support_levels.append(("weak", indicators["ma20"]))
            
            if indicators.get("ma60") is not None:
                support_levels.append(("weak", indicators["ma60"]))
            
            if indicators.get("boll_upper") is not None:
                resistance_levels.append(("strong", indicators["boll_upper"]))
            
            recent_high = max(highs[-20:]) if len(highs) >= 20 else max(highs)
            resistance_levels.append(("strong", recent_high))
            
            if indicators.get("ma20") is not None:
                resistance_levels.append(("weak", indicators["ma20"]))
            
            if indicators.get("ma60") is not None:
                resistance_levels.append(("weak", indicators["ma60"]))
            
            support_levels = self._deduplicate_levels(support_levels, ascending=True)
            resistance_levels = self._deduplicate_levels(resistance_levels, ascending=False)
            
            final_supports = [self._safe_value(level) for _, level in support_levels[:2]]
            final_resistances = [self._safe_value(level) for _, level in resistance_levels[:2]]
            
            final_supports = [s for s in final_supports if s is not None]
            final_resistances = [r for r in final_resistances if r is not None]
            
            return {
                "support": final_supports,
                "resistance": final_resistances
            }
            
        except Exception as e:
            logger.error(f"支撑压力位计算失败: {e}")
            return {"support": [], "resistance": []}
    
    def _deduplicate_levels(
        self,
        levels: List[tuple],
        ascending: bool = True
    ) -> List[tuple]:
        """
        去重并排序关键位
        
        Args:
            levels: [(强度, 价格), ...] 列表
            ascending: True=升序, False=降序
        
        Returns:
            去重排序后的列表
        """
        if not levels:
            return []
        
        strength_order = {"strong": 0, "weak": 1}
        
        sorted_levels = sorted(
            levels,
            key=lambda x: (strength_order.get(x[0], 2), x[1] if ascending else -x[1])
        )
        
        deduplicated = []
        for strength, price in sorted_levels:
            is_duplicate = False
            for existing_strength, existing_price in deduplicated:
                if abs(price - existing_price) / existing_price < 0.005:
                    is_duplicate = True
                    break
            
            if not is_duplicate:
                deduplicated.append((strength, price))
        
        return deduplicated
    
    def get_multi_period_levels(
        self,
        klines_5m: List[KLine],
        klines_15m: List[KLine],
        klines_1h: List[KLine],
        indicators_dict: Dict[str, Dict[str, float]]
    ) -> Dict[str, List[float]]:
        """
        整合多周期的支撑位和压力位
        
        Args:
            klines_5m: 5分钟K线
            klines_15m: 15分钟K线
            klines_1h: 1小时K线
            indicators_dict: 各周期指标字典 {"5m": {...}, "15m": {...}, "1h": {...}}
        
        Returns:
            整合后的关键位字典，适配KeyLevels结构
        """
        try:
            all_supports = []
            all_resistances = []
            
            for timeframe, klines in [("5m", klines_5m), ("15m", klines_15m), ("1h", klines_1h)]:
                indicators = indicators_dict.get(timeframe, {})
                levels = self.calc_support_resistance(klines, indicators)
                
                all_supports.extend(levels.get("support", []))
                all_resistances.extend(levels.get("resistance", []))
            
            unique_supports = list(set(all_supports))
            unique_supports.sort(reverse=True)
            
            unique_resistances = list(set(all_resistances))
            unique_resistances.sort()
            
            final_supports = unique_supports[:3]
            final_resistances = unique_resistances[:3]
            
            logger.info(
                f"✓ 关键位计算完成: "
                f"支撑位{len(final_supports)}个, "
                f"压力位{len(final_resistances)}个"
            )
            
            return {
                "supports": final_supports,
                "resistances": final_resistances
            }
            
        except Exception as e:
            logger.error(f"多周期关键位整合失败: {e}")
            return {"supports": [], "resistances": []}
    
    def format_indicators_for_ai(self, indicators: Dict[str, Dict[str, float]]) -> str:
        """
        格式化指标数据为AI可读的字符串
        
        Args:
            indicators: 指标字典
        
        Returns:
            格式化的指标字符串
        """
        lines = ["【技术指标】"]
        
        for timeframe, values in indicators.items():
            if not values:
                continue
            
            lines.append(f"\n{timeframe}周期:")
            
            # MA均线
            ma_values = []
            for key in ["ma5", "ma10", "ma20", "ma60"]:
                if key in values and values[key] is not None:
                    ma_values.append(f"{key.upper()}:{values[key]}")
            if ma_values:
                lines.append(f"  均线: {', '.join(ma_values)}")
            
            # EMA
            ema_values = []
            for key in ["ema12", "ema26"]:
                if key in values and values[key] is not None:
                    ema_values.append(f"{key.upper()}:{values[key]}")
            if ema_values:
                lines.append(f"  EMA: {', '.join(ema_values)}")
            
            # MACD
            if "macd" in values and values["macd"] is not None:
                lines.append(
                    f"  MACD: {values['macd']}, "
                    f"信号:{values.get('macd_signal', 'N/A')}, "
                    f"柱:{values.get('macd_hist', 'N/A')}"
                )
            
            # RSI
            if "rsi" in values and values["rsi"] is not None:
                rsi_status = "超买" if values["rsi"] > 70 else "超卖" if values["rsi"] < 30 else "中性"
                lines.append(f"  RSI: {values['rsi']} ({rsi_status})")
            
            # 布林带
            if "boll_middle" in values and values["boll_middle"] is not None:
                lines.append(
                    f"  BOLL: 上:{values.get('boll_upper', 'N/A')}, "
                    f"中:{values['boll_middle']}, "
                    f"下:{values.get('boll_lower', 'N/A')}"
                )
            
            # ATR
            if "atr" in values and values["atr"] is not None:
                lines.append(f"  ATR: {values['atr']}")
        
        return "\n".join(lines)
