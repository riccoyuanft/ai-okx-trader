"""Configuration settings management"""

from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Application settings"""
    
    # OKX API - 实盘
    okx_api_key: str = ""
    okx_secret_key: str = ""
    okx_passphrase: str = ""
    
    # OKX API - 模拟盘
    okx_simulated_api_key: str = ""
    okx_simulated_secret_key: str = ""
    okx_simulated_passphrase: str = ""
    
    # OKX 交易模式切换
    okx_testnet: bool = False
    
    # AI Config
    ai_provider: str = "qwen"  # openai 或 qwen
    openai_api_key: str
    openai_model: str = "gpt-4o"
    openai_base_url: str = "https://api.openai.com/v1"
    
    # 通义千问配置
    qwen_api_key: str = ""
    qwen_model: str = "qwen-plus"  # qwen-plus, qwen-turbo, qwen-max
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    
    # 豆包大模型配置
    doubao_api_key: str = ""
    doubao_model: str = "doubao-seed-1-8-251228"  # 豆包模型
    doubao_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    
    # Trading
    strategy_name: str = "15m_trend_following"  # 策略名称（对应strategies目录下的YAML文件，不含.yaml后缀）
    symbol_pool: str = "AUCTION-USDT,PRCL-USDT,KITE-USDT,ELF-USDT,ASTER-USDT,HYPE-USDT,LIT-USDT,ZAMA-USDT,IP-USDT,WLFI-USDT,FOGO-USDT,PARTI-USDT"  # 标的池（逗号分隔），为空时默认使用 BTC-USDT
    enable_auto_screening: bool = True  # 是否启用自动筛选标的（每2小时运行symbol_screener筛选全市场，覆盖symbol_pool配置）
    lock_timeout_cycles: int = 4  # 空仓锁定超时周期（单位：cycle_interval），4个周期=有持仓20min/无持仓60min
    trading_mode: str = "cash"
    initial_capital: float = 1000.0
    max_daily_risk_pct: float = 8.0
    cycle_interval_seconds: int = 300  # 有持仓时的AI更新间隔（5分钟）
    cycle_interval_no_position: int = 900  # 无持仓时的标的池扫描间隔（15分钟）
    
    # Strategy Parameters (可动态调整的策略参数)
    # 策略参数
    min_position_size_pct: float = 80.0  # 最小仓位比例
    max_position_size_pct: float = 100.0  # 最大仓位比例
    default_position_size_pct: float = 90.0  # 默认仓位比例
    
    # 均线周期
    ma_period_fast: int = 5   # 快速均线周期
    ma_period_mid: int = 10   # 中速均线周期
    ma_period_slow: int = 20  # 慢速均线周期
    
    # 盈亏比
    min_risk_reward_ratio: float = 1.5  # 最低盈亏比要求（15m短线，要求1:1.5+盈亏比）
    
    # 止损参数（代码级别校验用）
    initial_sl_min_distance_pct: float = 0.5  # 开仓时止损最小间距%（15m周期需要更宽止损空间）
    trailing_stop_atr_multiplier: float = 0.5  # 移动止损安全间距倍数
    trailing_stop_min_distance_pct: float = 0.3  # 移动止损最小间距%（匹配15m周期波动）
    
    # RSI阈值
    rsi_overbought: float = 70.0  # RSI超买阈值
    rsi_oversold: float = 30.0    # RSI超卖阈值
    
    # 风险管理
    max_consecutive_losses: int = 3  # 连续亏损次数限制（3次后减仓）
    loss_protection_position_pct: float = 50.0  # 连续亏损后的仓位限制（50%，不会太低导致无法盈利）
    
    # 量能参数
    vol_ma_period: int = 20  # 均量周期（VOL20）
    vol_break_threshold: float = 1.2  # 放量阈值（量能相对值>1.2判定为放量）
    vol_retrace_threshold: float = 1.0  # 缩量阈值（量能相对值<1.0判定为缩量）
    
    # 限价单执行参数
    limit_order_timeout: int = 120  # 限价单超时时间（秒），15m周期允许更久等待
    order_failed_cooling: int = 1  # 限价单失败后冷却时间（分钟），缩短冷却提高资金利用率
    
    # Redis (可选)
    use_redis: bool = True
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 8
    redis_password: Optional[str] = None
    
    # Alert
    webhook_url: Optional[str] = None
    alert_enabled: bool = False
    
    # DingTalk Notification
    dingtalk_webhook: Optional[str] = None
    dingtalk_secret: Optional[str] = None
    dingtalk_enabled: bool = False
    
    # Logging
    log_level: str = "INFO"
    log_file: str = "logs/ai_trader.log"
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"  # 忽略 .env 中的额外字段（如已废弃的 SYMBOL）


# Global settings instance
settings = Settings()
