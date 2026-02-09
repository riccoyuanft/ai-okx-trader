"""Database initialization script"""

import asyncio
import asyncpg
from loguru import logger
from src.config.settings import settings


async def create_tables():
    """Create database tables"""
    
    conn = await asyncpg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        database=settings.postgres_db,
        user=settings.postgres_user,
        password=settings.postgres_password,
    )
    
    try:
        # 交易记录表
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMP NOT NULL,
                symbol VARCHAR(20) NOT NULL,
                side VARCHAR(10) NOT NULL,
                entry_price DECIMAL(18, 8),
                exit_price DECIMAL(18, 8),
                size_usdt DECIMAL(18, 8),
                pnl_usdt DECIMAL(18, 8),
                pnl_pct DECIMAL(10, 4),
                stop_loss DECIMAL(18, 8),
                take_profit JSONB,
                reason TEXT,
                ai_decision JSONB,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        logger.info("Created table: trades")
        
        # K线历史表
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS klines (
                id SERIAL PRIMARY KEY,
                symbol VARCHAR(20) NOT NULL,
                timeframe VARCHAR(10) NOT NULL,
                timestamp BIGINT NOT NULL,
                open DECIMAL(18, 8),
                high DECIMAL(18, 8),
                low DECIMAL(18, 8),
                close DECIMAL(18, 8),
                volume DECIMAL(18, 8),
                UNIQUE(symbol, timeframe, timestamp)
            )
        """)
        logger.info("Created table: klines")
        
        # 风控日志表
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS risk_logs (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMP NOT NULL,
                event_type VARCHAR(50),
                details JSONB,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        logger.info("Created table: risk_logs")
        
        # 系统状态表
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS system_state (
                id SERIAL PRIMARY KEY,
                key VARCHAR(100) UNIQUE NOT NULL,
                value JSONB,
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        logger.info("Created table: system_state")
        
        # 创建索引
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp DESC);
            CREATE INDEX IF NOT EXISTS idx_klines_lookup ON klines(symbol, timeframe, timestamp DESC);
            CREATE INDEX IF NOT EXISTS idx_risk_logs_timestamp ON risk_logs(timestamp DESC);
        """)
        logger.info("Created indexes")
        
        logger.success("Database initialization completed successfully")
        
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        raise
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(create_tables())
