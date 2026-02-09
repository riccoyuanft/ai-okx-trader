"""
历史数据加载器
从OKX API获取历史K线数据并缓存
"""

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional
from loguru import logger

from src.data.okx_client import OKXClient
from src.data.models import KLine


class HistoricalDataLoader:
    """历史K线数据加载器"""
    
    def __init__(self, okx_client: OKXClient, cache_dir: str = "backtest/data/cache"):
        """
        初始化数据加载器
        
        Args:
            okx_client: OKX客户端实例
            cache_dir: 缓存目录路径
        """
        self.okx_client = okx_client
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"历史数据加载器已初始化，缓存目录: {self.cache_dir}")
    
    def load_klines(
        self,
        symbol: str,
        timeframe: str,
        start_date: str,
        end_date: str,
        use_cache: bool = True
    ) -> List[KLine]:
        """
        加载指定时间范围的K线数据
        
        Args:
            symbol: 交易对，如 "XAUT-USDT"
            timeframe: 时间周期，如 "5m", "15m", "1H"
            start_date: 开始日期，格式 "YYYY-MM-DD"
            end_date: 结束日期，格式 "YYYY-MM-DD"
            use_cache: 是否使用缓存
        
        Returns:
            K线列表，按时间升序排列
        """
        cache_file = self._get_cache_filename(symbol, timeframe, start_date, end_date)
        
        # 尝试从缓存加载
        if use_cache and cache_file.exists():
            logger.info(f"从缓存加载数据: {cache_file.name}")
            return self._load_from_cache(cache_file)
        
        # 从API获取数据
        logger.info(f"从OKX API获取数据: {symbol} {timeframe} {start_date} ~ {end_date}")
        klines = self._fetch_from_api(symbol, timeframe, start_date, end_date)
        
        # 保存到缓存
        if use_cache and klines:
            self._save_to_cache(cache_file, klines)
        
        return klines
    
    def _fetch_from_api(
        self,
        symbol: str,
        timeframe: str,
        start_date: str,
        end_date: str
    ) -> List[KLine]:
        """
        从OKX API批量获取历史数据
        
        OKX API限制：每次最多返回100根K线
        需要分批请求并合并
        """
        start_ts = int(datetime.strptime(start_date, "%Y-%m-%d").timestamp() * 1000)
        end_ts = int(datetime.strptime(end_date, "%Y-%m-%d").timestamp() * 1000)
        
        # 计算时间间隔（毫秒）
        interval_ms = self._get_interval_ms(timeframe)
        
        all_klines = []
        current_end = end_ts
        
        while current_end > start_ts:
            # OKX API每次最多100根
            limit = 100
            
            try:
                # 获取一批数据
                klines = self.okx_client.get_klines(
                    symbol=symbol,
                    timeframe=timeframe,
                    limit=limit,
                    end_time=current_end
                )
                
                if not klines:
                    break
                
                # 过滤时间范围内的数据
                valid_klines = [
                    k for k in klines
                    if start_ts <= k.timestamp <= end_ts
                ]
                
                all_klines.extend(valid_klines)
                
                # 更新时间指针
                oldest_ts = min(k.timestamp for k in klines)
                current_end = oldest_ts - interval_ms
                
                # 避免请求过快
                time.sleep(0.1)
                
                logger.debug(f"已获取 {len(all_klines)} 根K线")
                
            except Exception as e:
                logger.error(f"获取K线数据失败: {e}")
                break
        
        # 按时间升序排列
        all_klines.sort(key=lambda x: x.timestamp)
        
        logger.info(f"✓ 共获取 {len(all_klines)} 根K线")
        return all_klines
    
    def _get_interval_ms(self, timeframe: str) -> int:
        """获取时间周期对应的毫秒数"""
        intervals = {
            "1m": 60 * 1000,
            "5m": 5 * 60 * 1000,
            "15m": 15 * 60 * 1000,
            "30m": 30 * 60 * 1000,
            "1H": 60 * 60 * 1000,
            "4H": 4 * 60 * 60 * 1000,
            "1D": 24 * 60 * 60 * 1000,
        }
        return intervals.get(timeframe, 5 * 60 * 1000)
    
    def _get_cache_filename(
        self,
        symbol: str,
        timeframe: str,
        start_date: str,
        end_date: str
    ) -> Path:
        """生成缓存文件名"""
        filename = f"{symbol}_{timeframe}_{start_date}_{end_date}.json"
        return self.cache_dir / filename
    
    def _save_to_cache(self, cache_file: Path, klines: List[KLine]):
        """保存数据到缓存"""
        try:
            data = [k.model_dump() for k in klines]
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(f"✓ 数据已缓存: {cache_file.name}")
        except Exception as e:
            logger.error(f"保存缓存失败: {e}")
    
    def _load_from_cache(self, cache_file: Path) -> List[KLine]:
        """从缓存加载数据"""
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            klines = [KLine(**item) for item in data]
            logger.info(f"✓ 从缓存加载 {len(klines)} 根K线")
            return klines
        except Exception as e:
            logger.error(f"加载缓存失败: {e}")
            return []
    
    def clear_cache(self):
        """清空缓存"""
        for cache_file in self.cache_dir.glob("*.json"):
            cache_file.unlink()
        logger.info("✓ 缓存已清空")
