"""
加密货币标的自动筛选脚本
基于简化版超短线策略：快进快出、见好就收、灵活应变
适配 OKX 交易所现货市场

筛选原则（匹配简化prompt，不硬编码MA条件，让AI自主判断趋势）：
- 活跃度：最近4H 1H均量 ≥ 2万 USDT（超短线流动性保障）
- 波动率：1H ATR ≥ 0.8%，1H振幅 ≥ 1.2%（需要足够波动覆盖成本0.2%+利润0.1%）
- 结构：至少1个支撑或压力位（开仓依据：支撑位附近/突破回踩）
- 趋势：软评分（不硬过滤），只排除明确下跌趋势，其余交给AI判断
- 价格位置：软评分（不硬过滤），距支撑位越近分越高

评分机制：
- 活跃度 (25%) + 波动率 (30%) + 结构 (20%) + 趋势 (10%) + 价格位置 (15%)
- 高评分 (≥60分) = 优先交易
- 中评分 (40-59分) = 备选（交给AI判断）
- 低评分 (<40分) = 剔除

依赖安装：
pip install okx pandas numpy pandas-ta loguru
"""

import time
import pandas as pd
import numpy as np
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from loguru import logger
import sys
import csv

try:
    import okx.MarketData as MarketData
    import pandas_ta as ta
except ImportError as e:
    logger.error(f"依赖库未安装: {e}")
    logger.info("请运行: pip install okx pandas numpy pandas-ta loguru")
    sys.exit(1)


# ============================================================================
# 配置常量
# ============================================================================

class ScreenerConfig:
    """筛选器配置"""
    
    # OKX API配置（公开接口，无需密钥）
    OKX_FLAG = "0"  # 0=实盘, 1=模拟盘
    
    # 活跃度筛选（15m短线关注最近4~8小时活跃度）
    MIN_1H_AVG_VOLUME_USDT = 50_000  # 1H平均成交量 ≥ 5万 USDT（15m短线需要更好流动性）
    ACTIVITY_LOOKBACK_HOURS = 8  # 活跃度评估窗口：最近8根1H K线（约8小时）
    MAX_SPREAD_PCT = 0.15  # 买卖盘口价差 ≤ 0.15%（收紧，15m短线需要低滑点）
    
    # 市值安全（通过成交量和价格间接判断）
    MIN_PRICE_USDT = 0.01  # 最低价格，过滤极低价币
    
    # 波动率筛选（15m短线需要足够波动覆盖0.8%+利润目标）
    MIN_ATR_PCT = 1.0  # 1H ATR ≥ 1.0%（需要足够波动覆盖TP 0.8-1.5%）
    MIN_1H_RANGE_PCT = 1.5  # 1H振幅 ≥ 1.5%（确保有足够价格空间）
    MAX_1H_RANGE_PCT = 15.0  # 1H振幅 ≤ 15%（控制极端波动）
    
    # 价格位置筛选（避免追高接盘）
    MAX_PRICE_ABOVE_SUPPORT_PCT = 8.0  # 价格距离最近支撑位不超过8%（放宽，交给AI判断具体位置）
    MIN_PRICE_NEAR_SUPPORT_PCT = -3.0  # 价格可以略低于支撑位3%（回调机会）
    MAX_SHORT_TERM_GAIN_PCT = 15.0  # 最近10根1H K线涨幅不超过15%（放宽，允许上涨趋势中的标的）
    
    # 趋势规则（1H周期）
    TREND_TIMEFRAME = "1H"
    TREND_MA_PERIODS = [5, 10, 20]  # MA5 > MA10 > MA20
    
    # 择时辅助（15m周期）
    TIMING_TIMEFRAME = "15m"
    RSI_MIN = 25
    RSI_MAX = 75
    
    # 结构有效性（至少1个支撑或压力位）
    MIN_SUPPORT_OR_RESISTANCE = 1
    
    # 评分权重（15m短线：趋势更重要，需要明确方向）
    WEIGHT_ACTIVITY = 0.20  # 活跃度（流动性保障）
    WEIGHT_VOLATILITY = 0.25  # 波动率（覆盖成本+利润的基础）
    WEIGHT_STRUCTURE = 0.15  # 结构清晰度（支撑/压力位是开仓依据）
    WEIGHT_TREND = 0.25  # 趋势（15m短线需要更强趋势过滤）
    WEIGHT_POSITION = 0.15  # 价格位置（距支撑位越近越好）
    
    # 风险分级
    SCORE_HIGH = 60  # 优先交易
    SCORE_MID = 40   # 备选（交给AI判断）
    
    # 标的池大小限制（15m短线扫描间隔15min，可以适当增加池大小）
    MAX_MAIN_POOL_SIZE = 8   # 主池最多8个标的
    MAX_BACKUP_POOL_SIZE = 4  # 备选池最多4个标的
    
    # 数据获取
    KLINE_LIMIT_1H = 100  # 获取100根1H K线
    KLINE_LIMIT_15M = 120  # 获取120根15m K线
    
    # 输出
    OUTPUT_CSV = "symbol_whitelist.csv"
    
    # API请求延迟（避免频率限制）
    API_DELAY_SECONDS = 0.2


# ============================================================================
# 工具函数：API数据获取
# ============================================================================

class OKXDataFetcher:
    """OKX公开行情数据获取器"""
    
    def __init__(self):
        self.market_api = MarketData.MarketAPI(flag=ScreenerConfig.OKX_FLAG)
        logger.info("OKX MarketData API 已初始化（公开接口）")
    
    def get_all_spot_symbols(self) -> List[str]:
        """
        获取所有现货交易对（USDT本位）
        
        Returns:
            交易对列表，如 ['BTC-USDT', 'ETH-USDT', ...]
        """
        try:
            response = self.market_api.get_tickers(instType="SPOT")
            
            if response['code'] != '0':
                logger.error(f"获取交易对失败: {response}")
                return []
            
            symbols = []
            for ticker in response['data']:
                inst_id = ticker['instId']
                # 只保留 USDT 本位现货
                if inst_id.endswith('-USDT'):
                    symbols.append(inst_id)
            
            logger.info(f"获取到 {len(symbols)} 个 USDT 现货交易对")
            return symbols
            
        except Exception as e:
            logger.error(f"获取交易对异常: {e}")
            return []
    
    def get_24h_ticker(self, symbol: str) -> Optional[Dict]:
        """
        获取24小时行情数据
        
        Args:
            symbol: 交易对，如 'BTC-USDT'
        
        Returns:
            行情数据字典，包含成交量、价格等
        """
        try:
            response = self.market_api.get_ticker(instId=symbol)
            
            if response['code'] != '0' or not response['data']:
                return None
            
            ticker = response['data'][0]
            return {
                'symbol': symbol,
                'last_price': float(ticker['last']),
                'volume_24h_usdt': float(ticker['volCcy24h']),  # 24h成交量（计价货币）
                'bid_price': float(ticker['bidPx']),
                'ask_price': float(ticker['askPx']),
                'high_24h': float(ticker['high24h']),
                'low_24h': float(ticker['low24h']),
            }
            
        except Exception as e:
            logger.debug(f"获取 {symbol} 行情失败: {e}")
            return None
    
    def get_klines(self, symbol: str, timeframe: str, limit: int = 100) -> Optional[pd.DataFrame]:
        """
        获取K线数据
        
        Args:
            symbol: 交易对
            timeframe: 时间周期，如 '1H', '5m'
            limit: K线数量
        
        Returns:
            DataFrame，包含 timestamp, open, high, low, close, volume
        """
        try:
            response = self.market_api.get_candlesticks(
                instId=symbol,
                bar=timeframe,
                limit=str(limit)
            )
            
            if response['code'] != '0' or not response['data']:
                return None
            
            # OKX返回格式: [timestamp, open, high, low, close, volume, volCcy, volCcyQuote, confirm]
            df = pd.DataFrame(response['data'], columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'volCcy', 'volCcyQuote', 'confirm'
            ])
            
            # 转换数据类型
            df['timestamp'] = pd.to_datetime(df['timestamp'].astype(int), unit='ms')
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = df[col].astype(float)
            
            # 按时间升序排列
            df = df.sort_values('timestamp').reset_index(drop=True)
            
            return df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
            
        except Exception as e:
            logger.debug(f"获取 {symbol} K线失败: {e}")
            return None


# ============================================================================
# 工具函数：技术指标计算
# ============================================================================

class TechnicalAnalyzer:
    """技术指标计算器"""
    
    @staticmethod
    def calculate_ma(df: pd.DataFrame, periods: List[int]) -> pd.DataFrame:
        """计算多周期均线"""
        for period in periods:
            df[f'ma{period}'] = ta.sma(df['close'], length=period)
        return df
    
    @staticmethod
    def calculate_macd(df: pd.DataFrame) -> pd.DataFrame:
        """计算MACD指标"""
        macd = ta.macd(df['close'], fast=12, slow=26, signal=9)
        df['macd'] = macd['MACD_12_26_9']
        df['macd_signal'] = macd['MACDs_12_26_9']
        df['macd_hist'] = macd['MACDh_12_26_9']
        return df
    
    @staticmethod
    def calculate_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """计算RSI指标"""
        df['rsi'] = ta.rsi(df['close'], length=period)
        return df
    
    @staticmethod
    def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """计算ATR指标"""
        df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=period)
        return df
    
    @staticmethod
    def find_support_resistance(df: pd.DataFrame, window: int = 20) -> Tuple[List[float], List[float]]:
        """
        识别支撑位和压力位
        
        Args:
            df: K线数据
            window: 窗口大小
        
        Returns:
            (支撑位列表, 压力位列表)
        """
        if len(df) < window:
            return [], []
        
        # 使用最近的数据
        recent_df = df.tail(window)
        
        # 支撑位：局部最低点
        supports = []
        for i in range(1, len(recent_df) - 1):
            if (recent_df.iloc[i]['low'] < recent_df.iloc[i-1]['low'] and
                recent_df.iloc[i]['low'] < recent_df.iloc[i+1]['low']):
                supports.append(recent_df.iloc[i]['low'])
        
        # 压力位：局部最高点
        resistances = []
        for i in range(1, len(recent_df) - 1):
            if (recent_df.iloc[i]['high'] > recent_df.iloc[i-1]['high'] and
                recent_df.iloc[i]['high'] > recent_df.iloc[i+1]['high']):
                resistances.append(recent_df.iloc[i]['high'])
        
        # 去重并排序
        supports = sorted(list(set(supports)))
        resistances = sorted(list(set(resistances)), reverse=True)
        
        return supports, resistances


# ============================================================================
# 核心筛选逻辑
# ============================================================================

class SymbolScreener:
    """标的筛选器"""
    
    def __init__(self):
        self.fetcher = OKXDataFetcher()
        self.analyzer = TechnicalAnalyzer()
        self.config = ScreenerConfig()
    
    def screen_all_symbols(self) -> List[Dict]:
        """
        筛选所有交易对
        
        Returns:
            符合条件的标的列表，包含评分和详细信息
        """
        logger.info("=" * 80)
        logger.info("开始筛选加密货币标的...")
        logger.info("=" * 80)
        
        # 1. 获取所有交易对
        all_symbols = self.fetcher.get_all_spot_symbols()
        if not all_symbols:
            logger.error("未获取到交易对，退出")
            return []
        
        logger.info(f"待筛选交易对数量: {len(all_symbols)}")
        
        # 筛选统计
        stats = {
            'total': len(all_symbols),
            'liquidity_failed': 0,
            'volatility_failed': 0,
            'trend_failed': 0,
            'structure_failed': 0,
            'score_failed': 0,
            'passed': 0
        }
        
        # 2. 逐个筛选
        qualified_symbols = []
        
        for i, symbol in enumerate(all_symbols, 1):
            logger.info(f"\n[{i}/{len(all_symbols)}] 正在分析: {symbol}")
            
            try:
                result, fail_reason = self._screen_single_symbol_with_stats(symbol)
                if result:
                    qualified_symbols.append(result)
                    stats['passed'] += 1
                    logger.success(f"✓ {symbol} 通过筛选，评分: {result['score']:.1f}")
                else:
                    # 记录失败原因
                    if fail_reason:
                        stats[fail_reason] += 1
                    logger.debug(f"✗ {symbol} 未通过筛选: {fail_reason}")
                
                # API延迟
                time.sleep(self.config.API_DELAY_SECONDS)
                
            except Exception as e:
                logger.error(f"分析 {symbol} 时出错: {e}")
                continue
        
        # 3. 按评分排序
        qualified_symbols.sort(key=lambda x: x['score'], reverse=True)
        
        # 4. 输出统计信息
        logger.info("\n" + "=" * 80)
        logger.info(f"筛选完成！符合条件的标的数量: {len(qualified_symbols)}")
        logger.info("=" * 80)
        logger.info("\n筛选统计:")
        logger.info(f"  总标的数: {stats['total']}")
        logger.info(f"  流动性不足: {stats['liquidity_failed']} ({stats['liquidity_failed']/stats['total']*100:.1f}%)")
        logger.info(f"  波动率不符: {stats['volatility_failed']} ({stats['volatility_failed']/stats['total']*100:.1f}%)")
        logger.info(f"  趋势不符: {stats['trend_failed']} ({stats['trend_failed']/stats['total']*100:.1f}%)")
        logger.info(f"  结构不清晰: {stats['structure_failed']} ({stats['structure_failed']/stats['total']*100:.1f}%)")
        logger.info(f"  评分过低: {stats['score_failed']} ({stats['score_failed']/stats['total']*100:.1f}%)")
        logger.info(f"  通过筛选: {stats['passed']} ({stats['passed']/stats['total']*100:.1f}%)")
        logger.info("=" * 80)
        
        return qualified_symbols
    
    def _screen_single_symbol_with_stats(self, symbol: str) -> Tuple[Optional[Dict], Optional[str]]:
        """
        筛选单个交易对（带统计）
        
        Returns:
            (符合条件返回详细信息字典，失败原因)
        """
        # 1. 获取24h行情
        ticker = self.fetcher.get_24h_ticker(symbol)
        if not ticker:
            return None, None
        
        # 2. 基础流动性筛选
        if not self._check_liquidity(ticker):
            return None, 'liquidity_failed'
        
        # 3. 获取1H K线
        df_1h = self.fetcher.get_klines(symbol, self.config.TREND_TIMEFRAME, self.config.KLINE_LIMIT_1H)
        if df_1h is None or len(df_1h) < 50:
            return None, 'liquidity_failed'
        
        # 4. 获取5m K线
        df_5m = self.fetcher.get_klines(symbol, self.config.TIMING_TIMEFRAME, self.config.KLINE_LIMIT_15M)
        if df_5m is None or len(df_5m) < 50:
            return None, 'liquidity_failed'
        
        # 5. 计算技术指标
        df_1h = self._calculate_indicators_1h(df_1h)
        df_5m = self._calculate_indicators_5m(df_5m)
        
        # 6. 波动率筛选（硬过滤）
        volatility_score = self._check_volatility(df_1h)
        if volatility_score is None:
            return None, 'volatility_failed'
        
        # 7. 趋势评分（软评分，不硬过滤，AI自主判断）
        trend_score = self._check_trend(df_1h)
        
        # 8. 择时筛选（5m RSI风险提示）
        timing_pass, risk_warning = self._check_timing(df_5m)
        if not timing_pass:
            return None, 'trend_failed'
        
        # 9. 结构筛选（硬过滤：至少1个支撑/压力位）
        structure_score, supports, resistances = self._check_structure(df_1h)
        if structure_score is None:
            return None, 'structure_failed'
        
        # 10. 价格位置评分（软评分）
        position_score = self._check_price_position(df_1h, supports)
        if position_score is None:
            return None, 'score_failed'
        
        # 11. 活跃度评分
        activity_score = self._calculate_activity_score(df_1h)
        if activity_score is None:
            return None, 'activity_low'
        
        # 12. 综合评分（使用配置权重）
        total_score = (
            activity_score * self.config.WEIGHT_ACTIVITY +
            volatility_score * self.config.WEIGHT_VOLATILITY +
            structure_score * self.config.WEIGHT_STRUCTURE +
            trend_score * self.config.WEIGHT_TREND +
            position_score * self.config.WEIGHT_POSITION
        )
        
        # 11. 评分过滤
        if total_score < self.config.SCORE_MID:
            return None, 'score_failed'
        
        # 12. 风险分级
        if total_score >= self.config.SCORE_HIGH:
            risk_level = "优先交易"
        elif total_score >= self.config.SCORE_MID:
            risk_level = "备选"
        else:
            risk_level = "剔除"
        
        # 13. 计算短时成交量（最近N小时1H均量）
        lookback = self.config.ACTIVITY_LOOKBACK_HOURS
        recent_hours = df_1h.tail(lookback)
        short_term_vol = (recent_hours['close'] * recent_hours['volume']).mean()
        
        # 14. 返回结果
        return {
            'symbol': symbol,
            'score': total_score,
            'risk_level': risk_level,
            'price': ticker['last_price'],
            'volume_24h_usdt': ticker['volume_24h_usdt'],
            'short_term_vol_usdt': short_term_vol,
            'atr_pct': (df_1h['atr'].iloc[-1] / ticker['last_price']) * 100,
            'daily_range_pct': ((ticker['high_24h'] - ticker['low_24h']) / ticker['low_24h']) * 100,
            'ma5': df_1h['ma5'].iloc[-1],
            'ma10': df_1h['ma10'].iloc[-1],
            'ma20': df_1h['ma20'].iloc[-1],
            'macd': df_1h['macd'].iloc[-1],
            'rsi_5m': df_5m['rsi'].iloc[-1],
            'supports': supports[:3],
            'resistances': resistances[:3],
            'trend_status': 'bullish' if trend_score > 70 else 'neutral',
            'risk_warning': risk_warning,
        }, None
    
    def _screen_single_symbol(self, symbol: str) -> Optional[Dict]:
        """
        筛选单个交易对
        
        Returns:
            符合条件返回详细信息字典，否则返回None
        """
        # 1. 获取24h行情
        ticker = self.fetcher.get_24h_ticker(symbol)
        if not ticker:
            return None
        
        # 2. 基础流动性筛选
        if not self._check_liquidity(ticker):
            return None
        
        # 3. 获取1H K线
        df_1h = self.fetcher.get_klines(symbol, self.config.TREND_TIMEFRAME, self.config.KLINE_LIMIT_1H)
        if df_1h is None or len(df_1h) < 50:
            return None
        
        # 4. 获取5m K线
        df_5m = self.fetcher.get_klines(symbol, self.config.TIMING_TIMEFRAME, self.config.KLINE_LIMIT_15M)
        if df_5m is None or len(df_5m) < 50:
            return None
        
        # 5. 计算技术指标
        df_1h = self._calculate_indicators_1h(df_1h)
        df_5m = self._calculate_indicators_5m(df_5m)
        
        # 6. 波动率筛选
        volatility_score = self._check_volatility(df_1h)
        if volatility_score is None:
            return None
        
        # 7. 趋势评分（软评分）
        trend_score = self._check_trend(df_1h)
        
        # 8. 择时筛选（5m）
        timing_pass, risk_warning = self._check_timing(df_5m)
        if not timing_pass:
            return None
        
        # 9. 结构筛选
        structure_score, supports, resistances = self._check_structure(df_1h)
        if structure_score is None:
            return None
        
        # 10. 价格位置评分
        position_score = self._check_price_position(df_1h, supports)
        if position_score is None:
            return None
        
        # 11. 活跃度评分
        activity_score = self._calculate_activity_score(df_1h)
        if activity_score is None:
            return None
        
        # 12. 综合评分
        total_score = (
            activity_score * self.config.WEIGHT_ACTIVITY +
            volatility_score * self.config.WEIGHT_VOLATILITY +
            structure_score * self.config.WEIGHT_STRUCTURE +
            trend_score * self.config.WEIGHT_TREND +
            position_score * self.config.WEIGHT_POSITION
        )
        
        # 11. 评分过滤
        if total_score < self.config.SCORE_MID:
            return None
        
        # 12. 风险分级
        if total_score >= self.config.SCORE_HIGH:
            risk_level = "优先交易"
        elif total_score >= self.config.SCORE_MID:
            risk_level = "备选"
        else:
            risk_level = "剔除"
        
        # 13. 计算短时成交量（最近N小时1H均量）
        lookback = self.config.ACTIVITY_LOOKBACK_HOURS
        recent_hours = df_1h.tail(lookback)
        short_term_vol = (recent_hours['close'] * recent_hours['volume']).mean()
        
        # 14. 返回结果
        return {
            'symbol': symbol,
            'score': total_score,
            'risk_level': risk_level,
            'price': ticker['last_price'],
            'volume_24h_usdt': ticker['volume_24h_usdt'],
            'short_term_vol_usdt': short_term_vol,
            'atr_pct': (df_1h['atr'].iloc[-1] / ticker['last_price']) * 100,
            'daily_range_pct': ((ticker['high_24h'] - ticker['low_24h']) / ticker['low_24h']) * 100,
            'ma5': df_1h['ma5'].iloc[-1],
            'ma10': df_1h['ma10'].iloc[-1],
            'ma20': df_1h['ma20'].iloc[-1],
            'macd': df_1h['macd'].iloc[-1],
            'rsi_5m': df_5m['rsi'].iloc[-1],
            'supports': supports[:3],  # 最多3个支撑位
            'resistances': resistances[:3],  # 最多3个压力位
            'trend_status': 'bullish' if trend_score > 70 else 'neutral',
            'risk_warning': risk_warning,  # RSI极值风险提示
        }
    
    def _check_liquidity(self, ticker: Dict) -> bool:
        """检查基础流动性（价差和价格）"""
        # 买卖盘口价差
        spread_pct = ((ticker['ask_price'] - ticker['bid_price']) / ticker['bid_price']) * 100
        if spread_pct > self.config.MAX_SPREAD_PCT:
            return False
        
        # 价格过滤
        if ticker['last_price'] < self.config.MIN_PRICE_USDT:
            return False
        
        return True
    
    def _calculate_activity_score(self, df_1h: pd.DataFrame) -> Optional[float]:
        """计算短时活跃度评分 (0-100)，基于最近1~4小时1H平均成交量"""
        # 计算最近N根1H K线的平均成交量（USDT），超短线只看1~4小时
        lookback = self.config.ACTIVITY_LOOKBACK_HOURS
        recent_hours = df_1h.tail(lookback)
        avg_volume_usdt = (recent_hours['close'] * recent_hours['volume']).mean()
        
        # 活跃度筛选
        if avg_volume_usdt < self.config.MIN_1H_AVG_VOLUME_USDT:
            return None
        
        # 评分：对数标准化，2万=60分，20万=80分，200万=100分
        activity_score = min(100, 60 + (np.log10(avg_volume_usdt) - np.log10(20000)) * 40)
        
        return activity_score
    
    def _calculate_indicators_1h(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算1H周期指标"""
        df = self.analyzer.calculate_ma(df, self.config.TREND_MA_PERIODS)
        df = self.analyzer.calculate_macd(df)
        df = self.analyzer.calculate_atr(df)
        return df
    
    def _calculate_indicators_5m(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算5m周期指标"""
        df = self.analyzer.calculate_rsi(df)
        return df
    
    def _check_volatility(self, df_1h: pd.DataFrame) -> Optional[float]:
        """检查波动率（基于1H数据），返回评分或None"""
        latest = df_1h.iloc[-1]
        
        # 1H ATR筛选
        atr = latest['atr']
        atr_pct = (atr / latest['close']) * 100
        if atr_pct < self.config.MIN_ATR_PCT:
            return None
        
        # 计算最近10根1H K线的平均振幅
        recent_10h = df_1h.tail(10)
        avg_1h_range_pct = ((recent_10h['high'] - recent_10h['low']) / recent_10h['low'] * 100).mean()
        
        # 1H振幅筛选
        if avg_1h_range_pct < self.config.MIN_1H_RANGE_PCT or avg_1h_range_pct > self.config.MAX_1H_RANGE_PCT:
            return None
        
        # 评分：波动率越接近理想区间（4-8%）得分越高
        ideal_volatility = 6.0
        volatility_score = max(0, 100 - abs(avg_1h_range_pct - ideal_volatility) * 10)
        
        return volatility_score
    
    def _check_trend(self, df_1h: pd.DataFrame) -> float:
        """
        趋势软评分（永远返回评分，不硬过滤）
        简化策略：AI自主判断趋势，筛选器只提供参考分数
        - 强多头(MA5>MA10>MA20): 80-100分
        - 弱多头(价格>MA20或MA5>MA20): 50-80分
        - 横盘/不明确: 30-50分
        - 明确下跌(价格<MA20且MA20向下): 10-30分
        """
        latest_1h = df_1h.iloc[-1]
        prev_1h = df_1h.iloc[-2]
        
        trend_score = 50  # 基础分：中性
        
        # 价格与MA20的关系
        price_above_ma20 = latest_1h['close'] > latest_1h['ma20']
        ma20_rising = latest_1h['ma20'] > prev_1h['ma20']
        ma5_above_ma20 = latest_1h['ma5'] > latest_1h['ma20']
        strong_bullish = (latest_1h['ma5'] > latest_1h['ma10'] > latest_1h['ma20'])
        
        # MACD辅助
        macd_bullish = (latest_1h['macd'] > 0 and latest_1h['macd'] > latest_1h['macd_signal'])
        
        if strong_bullish:
            trend_score = 85
        elif price_above_ma20 and ma5_above_ma20:
            trend_score = 75
        elif price_above_ma20 or ma5_above_ma20:
            trend_score = 60
        elif not price_above_ma20 and not ma20_rising:
            trend_score = 20  # 明确下跌，低分但不排除
        else:
            trend_score = 40  # 横盘/不明确
        
        # MACD加分
        if macd_bullish:
            trend_score = min(100, trend_score + 10)
        
        return trend_score

    def _check_timing(self, df_5m: pd.DataFrame) -> Tuple[bool, str]:
        """检查5m择时，返回(是否通过, 风险提示)"""
        latest_rsi = df_5m['rsi'].iloc[-1]
        
        # RSI极值仅作风险提示，不过滤
        risk_warning = ""
        if latest_rsi < self.config.RSI_MIN:
            risk_warning = "RSI超卖"
        elif latest_rsi > self.config.RSI_MAX:
            risk_warning = "RSI超买"
        
        return True, risk_warning
    
    def _check_structure(self, df_1h: pd.DataFrame) -> Tuple[Optional[float], List[float], List[float]]:
        """检查结构有效性，返回(评分, 支撑位, 压力位)"""
        supports, resistances = self.analyzer.find_support_resistance(df_1h)
        
        # 至少1个支撑或压力位
        total_levels = len(supports) + len(resistances)
        if total_levels < self.config.MIN_SUPPORT_OR_RESISTANCE:
            return None, [], []
        
        # 结构清晰度评分
        structure_score = min(100, total_levels * 15 + 40)
        
        return structure_score, supports, resistances
    
    def _check_price_position(self, df_1h: pd.DataFrame, supports: List[float]) -> Optional[float]:
        """
        检查价格位置（软评分，不硬过滤）
        位置越好分越高，但不会直接返回None剔除标的
        具体入场位置交给AI判断
        """
        current_price = df_1h['close'].iloc[-1]
        
        # 1. 检查短期涨幅（最近4根1H K线，匹配超短线窗口）
        lookback = self.config.ACTIVITY_LOOKBACK_HOURS
        recent = df_1h.tail(max(lookback, 4))
        price_ago = recent['close'].iloc[0]
        short_term_gain_pct = ((current_price - price_ago) / price_ago) * 100
        
        # 短期涨幅过大仅降分，不硬过滤（超过阈值才返回None）
        if short_term_gain_pct > self.config.MAX_SHORT_TERM_GAIN_PCT * 1.5:
            return None  # 极端涨幅(>22.5%)才硬过滤
        
        # 2. 检查价格与支撑位的关系
        if not supports:
            position_score = 50
        else:
            nearest_support = min(supports, key=lambda s: abs(s - current_price))
            distance_pct = ((current_price - nearest_support) / nearest_support) * 100
            
            if self.config.MIN_PRICE_NEAR_SUPPORT_PCT <= distance_pct <= self.config.MAX_PRICE_ABOVE_SUPPORT_PCT:
                # 在支撑位附近，最佳位置
                position_score = max(60, 100 - abs(distance_pct) * 8)
            elif distance_pct > self.config.MAX_PRICE_ABOVE_SUPPORT_PCT:
                # 价格高于支撑位较远，降分但不硬过滤
                position_score = max(20, 60 - (distance_pct - self.config.MAX_PRICE_ABOVE_SUPPORT_PCT) * 5)
            else:
                # 价格低于支撑位，可能在回调
                position_score = 40
        
        # 3. 短期涨幅影响评分（涨幅越小越好）
        gain_penalty = max(0, short_term_gain_pct) * 1.5
        position_score = max(10, position_score - gain_penalty)
        
        return position_score


# ============================================================================
# 结果导出
# ============================================================================

class ResultExporter:
    """结果导出器"""
    
    @staticmethod
    def print_results(results: List[Dict]):
        """打印格式化结果到控制台"""
        if not results:
            logger.warning("无符合条件的标的")
            return
        
        logger.info("\n" + "=" * 120)
        logger.info("筛选结果汇总")
        logger.info("=" * 120)
        
        # 表头
        header = f"{'排名':<6}{'交易对':<15}{'评分':<8}{'风险等级':<12}{'价格':<12}{'近4H均量(万U)':<16}{'ATR%':<8}{'日振幅%':<10}{'风险提示':<12}"
        logger.info(header)
        logger.info("-" * 120)
        
        # 数据行
        for i, result in enumerate(results, 1):
            row = (
                f"{i:<6}"
                f"{result['symbol']:<15}"
                f"{result['score']:<8.1f}"
                f"{result['risk_level']:<12}"
                f"{result['price']:<12.4f}"
                f"{result['short_term_vol_usdt']/1e4:<16.2f}"
                f"{result['atr_pct']:<8.2f}"
                f"{result['daily_range_pct']:<10.2f}"
                f"{result.get('risk_warning', '-'):<12}"
            )
            logger.info(row)
        
        logger.info("=" * 120)
        
        # 统计信息
        high_risk = sum(1 for r in results if r['risk_level'] == '优先交易')
        mid_risk = sum(1 for r in results if r['risk_level'] == '备选')
        
        logger.info(f"\n统计信息:")
        logger.info(f"  优先交易: {high_risk} 个")
        logger.info(f"  备选: {mid_risk} 个")
        logger.info(f"  总计: {len(results)} 个")
    
    @staticmethod
    def export_to_csv(results: List[Dict], filename: str):
        """导出结果到CSV文件"""
        if not results:
            logger.warning("无数据可导出")
            return
        
        try:
            with open(filename, 'w', newline='', encoding='utf-8') as f:
                fieldnames = [
                    'symbol', 'score', 'risk_level', 'price', 'short_term_vol_usdt',
                    'volume_24h_usdt', 'atr_pct', 'daily_range_pct', 'ma5', 'ma10',
                    'ma20', 'macd', 'rsi_5m', 'supports', 'resistances',
                    'trend_status', 'risk_warning'
                ]
                
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                
                for result in results:
                    # 格式化支撑压力位
                    result_copy = result.copy()
                    result_copy['supports'] = ','.join([f"{s:.4f}" for s in result['supports']])
                    result_copy['resistances'] = ','.join([f"{r:.4f}" for r in result['resistances']])
                    writer.writerow(result_copy)
            
            logger.success(f"✓ 结果已导出到: {filename}")
            
        except Exception as e:
            logger.error(f"导出CSV失败: {e}")


# ============================================================================
# 主函数
# ============================================================================

def main():
    """主函数入口"""
    # 配置日志
    logger.remove()
    logger.add(
        sys.stdout,
        format="<green>{time:HH:mm:ss}</green> | <level>{level:<8}</level> | <level>{message}</level>",
        level="INFO"
    )
    
    logger.info("=" * 80)
    logger.info("加密货币标的自动筛选脚本")
    logger.info("\u7b56\u7565: \u5feb\u8fdb\u5feb\u51fa\u3001\u89c1\u597d\u5c31\u6536 | \u8f6f\u8d8b\u52bf+\u786c\u6ce2\u52a8+\u7ed3\u6784 | \u53ea\u505a\u591a\u73b0\u8d27")
    logger.info("=" * 80)
    
    # 创建筛选器
    screener = SymbolScreener()
    
    # 执行筛选
    results = screener.screen_all_symbols()
    
    # 输出结果
    ResultExporter.print_results(results)
    
    # 导出CSV
    if results:
        ResultExporter.export_to_csv(results, ScreenerConfig.OUTPUT_CSV)
    
    logger.info("\n筛选完成！")


if __name__ == "__main__":
    main()
