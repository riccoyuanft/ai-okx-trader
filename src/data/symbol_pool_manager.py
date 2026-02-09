"""动态标的池管理器 - 自动筛选、Redis存储、紧急更新"""

import json
import time
import threading
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple
from loguru import logger

from src.config.settings import settings


class SymbolPoolManager:
    """
    标的池自动化管理器
    
    职责：
    - 定期运行筛选逻辑，更新标的池（Redis存储）
    - 提供标的池查询、校验、切换接口
    - 紧急更新触发（行情走弱、波动率突变、评分下跌）
    - 最小更新间隔30分钟，避免频繁切换
    """
    
    # Redis键名
    POOL_KEY = "ai_trader:symbol_pool"           # 主标的池（高评分≥60）
    BACKUP_KEY = "ai_trader:symbol_pool_backup"   # 备选池（中评分40-59）
    LAST_UPDATE_KEY = "ai_trader:pool_last_update" # 上次更新时间戳
    POOL_SCORES_KEY = "ai_trader:pool_scores"     # 各标的评分详情
    
    # 更新间隔
    MIN_UPDATE_INTERVAL_SECONDS = 1800  # 最小更新间隔30分钟
    REGULAR_UPDATE_INTERVAL_SECONDS = 7200  # 常规更新2小时
    
    def __init__(self, redis_client=None):
        """
        初始化标的池管理器
        
        Args:
            redis_client: Redis连接实例（复用已有连接）
        """
        self.redis_client = redis_client
        self._screener = None  # 延迟初始化，避免循环导入
        self._lock = threading.Lock()  # 防止并发更新
        
    def _get_screener(self):
        """延迟加载筛选器（避免启动时重复初始化OKX API）"""
        if self._screener is None:
            from scripts.symbol_screener import SymbolScreener
            self._screener = SymbolScreener()
        return self._screener
    
    # ==================== 标的池查询接口 ====================
    
    def get_pool(self) -> List[str]:
        """
        获取当前标的池（高评分，按评分排序）
        
        优先从Redis读取，Redis无数据时降级到settings.py
        
        Returns:
            标的列表，如 ['HYPE-USDT', 'IP-USDT', ...]
        """
        if self.redis_client:
            try:
                data = self.redis_client.get(self.POOL_KEY)
                if data:
                    pool = json.loads(data)
                    if pool:
                        return pool
            except Exception as e:
                logger.warning(f"从Redis读取标的池失败: {e}")
        
        # 降级：从settings读取
        return self._get_settings_pool()
    
    def get_backup_pool(self) -> List[str]:
        """获取备选标的池（中评分）"""
        if self.redis_client:
            try:
                data = self.redis_client.get(self.BACKUP_KEY)
                if data:
                    return json.loads(data)
            except Exception:
                pass
        return []
    
    def get_all_available(self) -> List[str]:
        """获取所有可用标的（主池+备选池）"""
        return self.get_pool() + self.get_backup_pool()
    
    def get_scores(self) -> Dict[str, float]:
        """获取各标的评分"""
        if self.redis_client:
            try:
                data = self.redis_client.get(self.POOL_SCORES_KEY)
                if data:
                    return json.loads(data)
            except Exception:
                pass
        return {}
    
    def get_symbol_score(self, symbol: str) -> Optional[float]:
        """获取指定标的的评分"""
        scores = self.get_scores()
        return scores.get(symbol)
    
    def is_valid_symbol(self, symbol: str) -> bool:
        """检查标的是否在当前池内（主池+备选池）"""
        return symbol in self.get_all_available()
    
    def is_high_score(self, symbol: str) -> bool:
        """检查标的是否为高评分（≥60）"""
        return symbol in self.get_pool()
    
    def get_best_symbol(self, exclude: List[str] = None) -> Optional[str]:
        """
        获取评分最高的标的（排除指定标的）
        
        Args:
            exclude: 要排除的标的列表
        
        Returns:
            评分最高的可用标的，无可用标的返回None
        """
        exclude = exclude or []
        pool = self.get_pool()
        for symbol in pool:
            if symbol not in exclude:
                return symbol
        # 主池都被排除，尝试备选池
        for symbol in self.get_backup_pool():
            if symbol not in exclude:
                return symbol
        return None
    
    # ==================== 标的池更新接口 ====================
    
    def refresh_pool(self, force: bool = False) -> bool:
        """
        执行筛选并更新标的池
        
        Args:
            force: 是否强制更新（忽略最小间隔）
        
        Returns:
            是否成功更新
        """
        if not force and not self._can_update():
            logger.info("📊 标的池更新间隔不足30分钟，跳过")
            return False
        
        if not self._lock.acquire(blocking=False):
            logger.info("📊 标的池正在更新中，跳过重复请求")
            return False
        
        try:
            logger.info("=" * 60)
            logger.info("📊 开始自动筛选标的池...")
            logger.info("=" * 60)
            
            screener = self._get_screener()
            results = screener.screen_all_symbols()
            
            if not results:
                logger.warning("⚠️ 筛选结果为空，沿用上次标的池")
                return False
            
            # 分离高评分和中评分
            from scripts.symbol_screener import ScreenerConfig
            config = ScreenerConfig()
            
            high_pool = []  # ≥60分
            backup_pool = []  # 40-59分
            scores = {}
            
            for r in results:
                symbol = r['symbol']
                score = r['score']
                scores[symbol] = score
                
                if score >= config.SCORE_HIGH:
                    high_pool.append(symbol)
                elif score >= config.SCORE_MID:
                    backup_pool.append(symbol)
            
            # 按评分排序取top N（结果已按评分排序，直接截断）
            max_main = getattr(config, 'MAX_MAIN_POOL_SIZE', 5)
            max_backup = getattr(config, 'MAX_BACKUP_POOL_SIZE', 3)
            high_pool = high_pool[:max_main]
            backup_pool = backup_pool[:max_backup]
            
            # 保存到Redis
            self._save_pool(high_pool, backup_pool, scores)
            
            logger.success(f"✓ 标的池更新完成: 主池{len(high_pool)}个(上限{max_main}), 备选{len(backup_pool)}个(上限{max_backup})")
            if high_pool:
                logger.info(f"  主池: {', '.join(high_pool)}")
            if backup_pool:
                logger.info(f"  备选: {', '.join(backup_pool)}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ 标的池筛选失败: {e}，沿用历史池")
            return False
        finally:
            self._lock.release()
    
    def _save_pool(self, high_pool: List[str], backup_pool: List[str], scores: Dict[str, float]):
        """保存标的池到Redis"""
        if not self.redis_client:
            return
        
        try:
            pipe = self.redis_client.pipeline()
            pipe.set(self.POOL_KEY, json.dumps(high_pool))
            pipe.set(self.BACKUP_KEY, json.dumps(backup_pool))
            pipe.set(self.POOL_SCORES_KEY, json.dumps(scores))
            pipe.set(self.LAST_UPDATE_KEY, str(time.time()))
            pipe.execute()
        except Exception as e:
            logger.error(f"保存标的池到Redis失败: {e}")
    
    def _can_update(self) -> bool:
        """检查是否满足最小更新间隔"""
        if not self.redis_client:
            return True
        
        try:
            last_update = self.redis_client.get(self.LAST_UPDATE_KEY)
            if not last_update:
                return True
            
            elapsed = time.time() - float(last_update)
            return elapsed >= self.MIN_UPDATE_INTERVAL_SECONDS
        except Exception:
            return True
    
    def get_last_update_time(self) -> Optional[datetime]:
        """获取上次更新时间"""
        if not self.redis_client:
            return None
        
        try:
            ts = self.redis_client.get(self.LAST_UPDATE_KEY)
            if ts:
                return datetime.fromtimestamp(float(ts))
        except Exception:
            pass
        return None
    
    def seconds_since_last_update(self) -> float:
        """距上次更新的秒数"""
        if not self.redis_client:
            return float('inf')
        
        try:
            ts = self.redis_client.get(self.LAST_UPDATE_KEY)
            if ts:
                return time.time() - float(ts)
        except Exception:
            pass
        return float('inf')
    
    # ==================== 紧急更新检测 ====================
    
    def check_emergency_update(self, 
                                current_symbol: str,
                                current_pnl_pct: float = 0,
                                holding_minutes: float = 0,
                                current_atr_pct: float = 0,
                                prev_atr_pct: float = 0) -> Tuple[bool, str]:
        """
        检查是否需要紧急更新标的池
        
        Args:
            current_symbol: 当前交易标的
            current_pnl_pct: 当前浮盈百分比
            holding_minutes: 持仓分钟数
            current_atr_pct: 当前1H ATR百分比
            prev_atr_pct: 前一次1H ATR百分比
        
        Returns:
            (是否需要更新, 原因)
        """
        # 条件①：浮亏≥0.5%且持仓≥15分钟
        if current_pnl_pct <= -0.5 and holding_minutes >= 15:
            return True, f"标的{current_symbol}浮亏{current_pnl_pct:.2f}%且持仓{holding_minutes:.0f}分钟"
        
        # 条件②：波动率突变(ATR变动≥0.3%)
        if prev_atr_pct > 0 and abs(current_atr_pct - prev_atr_pct) >= 0.3:
            return True, f"波动率突变: ATR {prev_atr_pct:.2f}% → {current_atr_pct:.2f}%"
        
        # 条件③：当前标的评分跌至<40
        score = self.get_symbol_score(current_symbol)
        if score is not None and score < 40:
            return True, f"{current_symbol}评分跌至{score:.1f}<40"
        
        return False, ""
    
    # ==================== 每日重置 ====================
    
    def daily_reset_if_needed(self):
        """每日UTC 0点（北京时间8点）全量刷新"""
        now = datetime.utcnow()
        last_update = self.get_last_update_time()
        
        if last_update is None:
            self.refresh_pool(force=True)
            return
        
        # 检查是否跨过UTC 0点
        last_utc = last_update.replace(tzinfo=None) if last_update.tzinfo else last_update
        if now.date() > last_utc.date():
            logger.info("📊 跨日检测：执行每日全量标的池刷新")
            self.refresh_pool(force=True)
    
    # ==================== 内部工具 ====================
    
    @staticmethod
    def _get_settings_pool() -> List[str]:
        """从settings.py读取标的池（降级方案）"""
        pool_str = getattr(settings, 'symbol_pool', '')
        if pool_str:
            return [s.strip() for s in pool_str.split(',') if s.strip()]
        return [settings.symbol]
