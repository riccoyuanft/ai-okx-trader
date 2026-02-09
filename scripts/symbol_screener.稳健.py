"""
加密货币标的自动筛选脚本
基于 1H 主周期 + 5m 择时的超短线交易策略
适配 OKX 交易所现货市场

策略核心（已优化，提高筛选通过率）：
- 1H K线：趋势核心判断（分级判定：强多头/弱多头）
  * 强多头：MA5>MA10>MA20标准多头排列（评分70-100）
  * 弱多头：MA5>MA10 或 价格站上MA20且MA20向上（评分50-75）
  * MACD零轴上方多头状态可额外加分
- 5m K线：择时辅助（RSI中性区间，仅作风险提示）
- 流动性：24h成交量 ≥ 2000万 USDT（已降低）
- 波动率：1H ATR ≥ 1.0%，日内振幅 2%-30%（已放宽）
- 结构：至少1个支撑或压力位

评分机制：
- 流动性 (30%) + 波动率 (20%) + 趋势质量 (25%) + 结构清晰度 (25%)
- 高评分 (≥75分) = 优先交易（强多头趋势）
- 中评分 (50-74分) = 备选（弱多头趋势或强多头但其他指标一般）
- 低评分 (<50分) = 剔除

优化说明：
1. 趋势判定升级为分级判定（强多头/弱多头），与交易策略一致
2. MACD条件从"刚好金叉"改为"持续多头状态"，避免错过机会
3. 流动性门槛从5000万降至2000万USDT，扩大标的池
4. 波动率下限从1.5%降至1.0%，保留更多活跃标的
5. 评分门槛从60分降至50分，增加备选标的数量

依赖安装：
pip install okx pandas numpy ta-lib loguru
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
    import talib
except ImportError as e:
    logger.error(f"依赖库未安装: {e}")
    logger.info("请运行: pip install okx pandas numpy ta-lib loguru")
    sys.exit(1)


# ============================================================================
# 配置常量
# ============================================================================

class ScreenerConfig:
    """筛选器配置"""
    
    # OKX API配置（公开接口，无需密钥）
    OKX_FLAG = "0"  # 0=实盘, 1=模拟盘
    
    # 流动性筛选（降低门槛，扩大标的池）
    MIN_24H_VOLUME_USDT = 20_000_000  # 2000万 USDT（从5000万降低）
    MAX_SPREAD_PCT = 0.15  # 买卖盘口价差 ≤ 0.15%（从0.1%放宽）
    
    # 市值安全（通过成交量和价格间接判断）
    MIN_PRICE_USDT = 0.01  # 最低价格，过滤极低价币
    
    # 波动率筛选（降低下限，保留活跃标的）
    MIN_ATR_PCT = 1.0  # 1H ATR ≥ 1.0%（从1.5%降低）
    MIN_DAILY_RANGE_PCT = 2.0  # 日内振幅 ≥ 2%（从3%降低）
    MAX_DAILY_RANGE_PCT = 30.0  # 日内振幅 ≤ 30%（从25%放宽）
    
    # 趋势规则（1H周期）
    TREND_TIMEFRAME = "1H"
    TREND_MA_PERIODS = [5, 10, 20]  # MA5 > MA10 > MA20
    
    # 择时辅助（5m周期）
    TIMING_TIMEFRAME = "5m"
    RSI_MIN = 25
    RSI_MAX = 75
    
    # 结构有效性（至少1个支撑或压力位）
    MIN_SUPPORT_OR_RESISTANCE = 1
    
    # 评分权重
    WEIGHT_LIQUIDITY = 0.30
    WEIGHT_VOLATILITY = 0.20
    WEIGHT_TREND = 0.25
    WEIGHT_STRUCTURE = 0.25
    
    # 风险分级（降低门槛，扩大标的池）
    SCORE_HIGH = 75  # 优先交易（从80降低）
    SCORE_MID = 50   # 备选（从60降低）
    
    # 数据获取
    KLINE_LIMIT_1H = 100  # 获取100根1H K线
    KLINE_LIMIT_5M = 120  # 获取120根5m K线
    
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
            df[f'ma{period}'] = talib.SMA(df['close'].values, timeperiod=period)
        return df
    
    @staticmethod
    def calculate_macd(df: pd.DataFrame) -> pd.DataFrame:
        """计算MACD指标"""
        macd, signal, hist = talib.MACD(
            df['close'].values,
            fastperiod=12,
            slowperiod=26,
            signalperiod=9
        )
        df['macd'] = macd
        df['macd_signal'] = signal
        df['macd_hist'] = hist
        return df
    
    @staticmethod
    def calculate_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """计算RSI指标"""
        df['rsi'] = talib.RSI(df['close'].values, timeperiod=period)
        return df
    
    @staticmethod
    def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """计算ATR指标"""
        df['atr'] = talib.ATR(
            df['high'].values,
            df['low'].values,
            df['close'].values,
            timeperiod=period
        )
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
        df_5m = self.fetcher.get_klines(symbol, self.config.TIMING_TIMEFRAME, self.config.KLINE_LIMIT_5M)
        if df_5m is None or len(df_5m) < 50:
            return None, 'liquidity_failed'
        
        # 5. 计算技术指标
        df_1h = self._calculate_indicators_1h(df_1h)
        df_5m = self._calculate_indicators_5m(df_5m)
        
        # 6. 波动率筛选
        volatility_score = self._check_volatility(df_1h, ticker)
        if volatility_score is None:
            return None, 'volatility_failed'
        
        # 7. 趋势筛选（1H）
        trend_score = self._check_trend(df_1h)
        if trend_score is None:
            return None, 'trend_failed'
        
        # 8. 择时筛选（5m）
        timing_pass, risk_warning = self._check_timing(df_5m)
        if not timing_pass:
            return None, 'trend_failed'
        
        # 9. 结构筛选
        structure_score, supports, resistances = self._check_structure(df_1h)
        if structure_score is None:
            return None, 'structure_failed'
        
        # 10. 计算综合评分
        liquidity_score = self._calculate_liquidity_score(ticker)
        total_score = (
            liquidity_score * self.config.WEIGHT_LIQUIDITY +
            volatility_score * self.config.WEIGHT_VOLATILITY +
            trend_score * self.config.WEIGHT_TREND +
            structure_score * self.config.WEIGHT_STRUCTURE
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
        
        # 13. 返回结果
        return {
            'symbol': symbol,
            'score': total_score,
            'risk_level': risk_level,
            'price': ticker['last_price'],
            'volume_24h_usdt': ticker['volume_24h_usdt'],
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
        df_5m = self.fetcher.get_klines(symbol, self.config.TIMING_TIMEFRAME, self.config.KLINE_LIMIT_5M)
        if df_5m is None or len(df_5m) < 50:
            return None
        
        # 5. 计算技术指标
        df_1h = self._calculate_indicators_1h(df_1h)
        df_5m = self._calculate_indicators_5m(df_5m)
        
        # 6. 波动率筛选
        volatility_score = self._check_volatility(df_1h, ticker)
        if volatility_score is None:
            return None
        
        # 7. 趋势筛选（1H）
        trend_score = self._check_trend(df_1h)
        if trend_score is None:
            return None
        
        # 8. 择时筛选（5m）
        timing_pass, risk_warning = self._check_timing(df_5m)
        if not timing_pass:
            return None
        
        # 9. 结构筛选
        structure_score, supports, resistances = self._check_structure(df_1h)
        if structure_score is None:
            return None
        
        # 10. 计算综合评分
        liquidity_score = self._calculate_liquidity_score(ticker)
        total_score = (
            liquidity_score * self.config.WEIGHT_LIQUIDITY +
            volatility_score * self.config.WEIGHT_VOLATILITY +
            trend_score * self.config.WEIGHT_TREND +
            structure_score * self.config.WEIGHT_STRUCTURE
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
        
        # 13. 返回结果
        return {
            'symbol': symbol,
            'score': total_score,
            'risk_level': risk_level,
            'price': ticker['last_price'],
            'volume_24h_usdt': ticker['volume_24h_usdt'],
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
        """检查流动性"""
        # 24h成交量
        if ticker['volume_24h_usdt'] < self.config.MIN_24H_VOLUME_USDT:
            return False
        
        # 买卖盘口价差
        spread_pct = ((ticker['ask_price'] - ticker['bid_price']) / ticker['bid_price']) * 100
        if spread_pct > self.config.MAX_SPREAD_PCT:
            return False
        
        # 价格过滤
        if ticker['last_price'] < self.config.MIN_PRICE_USDT:
            return False
        
        return True
    
    def _calculate_liquidity_score(self, ticker: Dict) -> float:
        """计算流动性评分 (0-100)"""
        # 成交量评分（对数标准化）
        volume_score = min(100, (np.log10(ticker['volume_24h_usdt']) - 8) * 20)
        
        # 价差评分
        spread_pct = ((ticker['ask_price'] - ticker['bid_price']) / ticker['bid_price']) * 100
        spread_score = max(0, 100 - spread_pct * 2000)
        
        return (volume_score * 0.7 + spread_score * 0.3)
    
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
    
    def _check_volatility(self, df_1h: pd.DataFrame, ticker: Dict) -> Optional[float]:
        """检查波动率，返回评分或None"""
        current_price = ticker['last_price']
        atr = df_1h['atr'].iloc[-1]
        atr_pct = (atr / current_price) * 100
        
        # ATR筛选
        if atr_pct < self.config.MIN_ATR_PCT:
            return None
        
        # 日内振幅筛选
        daily_range_pct = ((ticker['high_24h'] - ticker['low_24h']) / ticker['low_24h']) * 100
        if daily_range_pct < self.config.MIN_DAILY_RANGE_PCT or daily_range_pct > self.config.MAX_DAILY_RANGE_PCT:
            return None
        
        # 评分：波动率越接近理想区间（8-15%）得分越高
        ideal_volatility = 10.0
        volatility_score = max(0, 100 - abs(daily_range_pct - ideal_volatility) * 5)
        
        return volatility_score
    
    def _check_trend(self, df_1h: pd.DataFrame) -> Optional[float]:
        """检查1H趋势（分级判定），返回评分或None"""
        latest = df_1h.iloc[-1]
        prev = df_1h.iloc[-2]
        
        # 强多头趋势：MA5 > MA10 > MA20标准多头排列（优先级最高）
        strong_bullish = (latest['ma5'] > latest['ma10'] > latest['ma20'])
        
        # 弱多头趋势：MA5 > MA10 或 价格站上MA20且MA20向上
        weak_bullish_ma = (latest['ma5'] > latest['ma10'])
        price_above_ma20 = (latest['close'] > latest['ma20'])
        ma20_upward = (latest['ma20'] > prev['ma20'])
        weak_bullish_price = (price_above_ma20 and ma20_upward)
        weak_bullish = (weak_bullish_ma or weak_bullish_price) and not strong_bullish
        
        # 辅助条件：MACD零轴上方多头状态（可提升评分）
        macd_bullish = (
            latest['macd'] > 0 and
            latest['macd'] > latest['macd_signal']
        )
        
        # 趋势判定：至少满足弱多头
        if not (strong_bullish or weak_bullish):
            return None
        
        # 趋势质量评分（分级评分）
        if strong_bullish:
            # 强多头：基础分70，根据MA间距加分
            ma_gap_5_10 = ((latest['ma5'] - latest['ma10']) / latest['ma10']) * 100
            ma_gap_10_20 = ((latest['ma10'] - latest['ma20']) / latest['ma20']) * 100
            trend_score = min(100, 70 + (ma_gap_5_10 + ma_gap_10_20) * 10)
            # MACD多头可额外加分
            if macd_bullish:
                trend_score = min(100, trend_score + 5)
        else:
            # 弱多头：基础分50-65
            if weak_bullish_ma and weak_bullish_price:
                # 两个条件都满足，评分较高
                trend_score = 65
            else:
                # 只满足一个条件
                trend_score = 55
            # MACD多头可额外加分
            if macd_bullish:
                trend_score = min(100, trend_score + 10)
        
        return max(60, trend_score)  # 通过筛选的最低60分

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
        header = f"{'排名':<6}{'交易对':<15}{'评分':<8}{'风险等级':<12}{'价格':<12}{'24h成交量(千万U)':<18}{'ATR%':<8}{'日振幅%':<10}{'风险提示':<12}"
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
                f"{result['volume_24h_usdt']/1e7:<18.2f}"
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
                    'symbol', 'score', 'risk_level', 'price', 'volume_24h_usdt',
                    'atr_pct', 'daily_range_pct', 'ma5', 'ma10', 'ma20', 'macd',
                    'rsi_5m', 'supports', 'resistances', 'trend_status', 'risk_warning'
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
    logger.info("策略: 1H主周期 + 5m择时 | 激进求稳 | 只做多现货")
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
