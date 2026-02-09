"""OKX API client wrapper"""

import okx.Trade as Trade
import okx.MarketData as MarketData
import okx.Account as Account
from loguru import logger
from typing import List, Dict, Optional
from src.config.settings import settings
from src.data.models import KLine, Position


class OKXClient:
    """OKX API客户端封装"""
    
    def __init__(self):
        flag = "1" if settings.okx_testnet else "0"
        
        # 根据模式选择对应的API Key
        if settings.okx_testnet:
            api_key = settings.okx_simulated_api_key
            secret_key = settings.okx_simulated_secret_key
            passphrase = settings.okx_simulated_passphrase
            mode_name = "模拟盘"
        else:
            api_key = settings.okx_api_key
            secret_key = settings.okx_secret_key
            passphrase = settings.okx_passphrase
            mode_name = "实盘"
        
        self.market_api = MarketData.MarketAPI(
            api_key=api_key,
            api_secret_key=secret_key,
            passphrase=passphrase,
            flag=flag,
            debug=False
        )
        
        self.trade_api = Trade.TradeAPI(
            api_key=api_key,
            api_secret_key=secret_key,
            passphrase=passphrase,
            flag=flag,
            debug=False
        )
        
        self.account_api = Account.AccountAPI(
            api_key=api_key,
            api_secret_key=secret_key,
            passphrase=passphrase,
            flag=flag,
            debug=False
        )
        
        logger.info(f"OKX Client initialized ({mode_name}, testnet={settings.okx_testnet})")
    
    def get_klines(self, symbol: str, timeframe: str, limit: int = 100) -> List[KLine]:
        """
        获取K线数据
        
        Args:
            symbol: 交易对 (如 BTC-USDT)
            timeframe: 时间周期 (5m, 15m, 1H)
            limit: 数量限制
        
        Returns:
            K线列表
        """
        try:
            response = self.market_api.get_candlesticks(
                instId=symbol,
                bar=timeframe,
                limit=str(limit)
            )
            
            if response['code'] != '0':
                logger.error(f"Failed to get klines: {response['msg']}")
                return []
            
            klines = []
            for item in response['data']:
                klines.append(KLine(
                    timestamp=int(item[0]),
                    open=float(item[1]),
                    high=float(item[2]),
                    low=float(item[3]),
                    close=float(item[4]),
                    volume=float(item[5])
                ))
            
            return klines
            
        except Exception as e:
            logger.error(f"Error getting klines: {e}")
            return []
    
    def get_current_price(self, symbol: str) -> Optional[float]:
        """获取当前价格"""
        try:
            response = self.market_api.get_ticker(instId=symbol)
            
            if response['code'] != '0':
                logger.error(f"Failed to get price: {response['msg']}")
                return None
            
            return float(response['data'][0]['last'])
            
        except Exception as e:
            logger.error(f"Error getting price: {e}")
            return None
    
    def get_position(self, symbol: str) -> Position:
        """获取当前持仓（现货模式通过余额判断，合约模式通过持仓API）"""
        try:
            # 现货交易模式：通过余额判断持仓
            if settings.trading_mode == "cash":
                # 提取基础货币（如 BTC-USDT -> BTC）
                base_currency = symbol.split('-')[0]
                
                # 查询基础货币余额
                balance_response = self.account_api.get_account_balance(ccy=base_currency)
                
                if balance_response['code'] != '0':
                    logger.error(f"Failed to get balance: {balance_response['msg']}")
                    return Position(has_position=False)
                
                if not balance_response['data']:
                    return Position(has_position=False)
                
                # 查找基础货币余额
                base_balance = 0.0
                for detail in balance_response['data'][0]['details']:
                    if detail['ccy'] == base_currency:
                        base_balance = float(detail.get('availBal', 0))
                        break
                
                # 获取当前价格，检查是否为有效持仓
                current_price = self.get_current_price(symbol)
                if not current_price:
                    return Position(has_position=False)
                
                # 计算持仓价值，低于5 USDT视为灰尘余额（无法交易）
                position_value = base_balance * current_price
                min_tradable_value = 5.0  # OKX最小订单金额
                
                if position_value < min_tradable_value:
                    logger.debug(f"检测到灰尘余额: {base_balance} {base_currency} = {position_value:.4f} USDT (低于{min_tradable_value} USDT，忽略)")
                    return Position(has_position=False)
                
                size_usdt = position_value
                
                # 现货模式无法获取平均入场价，使用当前价格作为参考
                # 注意：这里的盈亏计算需要从历史订单或Redis状态中获取真实入场价
                return Position(
                    has_position=True,
                    entry_price=current_price,  # 临时使用当前价格
                    size_usdt=size_usdt,
                    current_pnl_pct=0.0  # 无法计算准确盈亏
                )
            
            # 合约交易模式：使用持仓API
            else:
                response = self.account_api.get_positions(instId=symbol)
                
                if response['code'] != '0':
                    logger.error(f"Failed to get position: {response['msg']}")
                    return Position(has_position=False)
                
                if not response['data']:
                    return Position(has_position=False)
                
                pos_data = response['data'][0]
                pos_size = float(pos_data.get('pos', 0))
                
                if pos_size == 0:
                    return Position(has_position=False)
                
                avg_price = float(pos_data.get('avgPx', 0))
                current_price = self.get_current_price(symbol)
                
                if current_price and avg_price > 0:
                    pnl_pct = ((current_price - avg_price) / avg_price) * 100
                else:
                    pnl_pct = 0.0
                
                return Position(
                    has_position=True,
                    entry_price=avg_price,
                    size_usdt=pos_size * avg_price,
                    current_pnl_pct=pnl_pct
                )
            
        except Exception as e:
            logger.error(f"Error getting position: {e}")
            return Position(has_position=False)
    
    def get_balance(self, currency: str = "USDT") -> float:
        """获取账户余额"""
        try:
            response = self.account_api.get_account_balance(ccy=currency)
            
            if response['code'] != '0':
                logger.error(f"Failed to get balance: {response['msg']}")
                return 0.0
            
            if not response['data']:
                return 0.0
            
            for detail in response['data'][0]['details']:
                if detail['ccy'] == currency:
                    return float(detail['availBal'])
            
            return 0.0
            
        except Exception as e:
            logger.error(f"Error getting balance: {e}")
            return 0.0
    
    def place_limit_order(
        self,
        symbol: str,
        side: str,
        price: float,
        size: float
    ) -> Optional[str]:
        """
        下限价单
        
        Args:
            symbol: 交易对
            side: buy/sell
            price: 价格
            size: 数量(USDT)
        
        Returns:
            订单ID
        """
        try:
            response = self.trade_api.place_order(
                instId=symbol,
                tdMode=settings.trading_mode,
                side=side,
                ordType="limit",
                px=str(price),
                sz=str(size)
            )
            
            if response['code'] != '0':
                logger.error(f"Failed to place order: {response['msg']}")
                return None
            
            order_id = response['data'][0]['ordId']
            logger.info(f"Order placed: {side} {symbol} {size} @ {price}, ordId={order_id}")
            return order_id
            
        except Exception as e:
            logger.error(f"Error placing order: {e}")
            return None
    
    def place_market_order(
        self,
        symbol: str,
        side: str,
        size: float,
        use_quote_ccy: bool = False
    ) -> Optional[str]:
        """
        下市价单
        
        Args:
            symbol: 交易对
            side: buy/sell
            size: 数量（买入时如果use_quote_ccy=True则为USDT金额，否则为币数量）
            use_quote_ccy: 买入时是否使用计价货币(USDT)作为数量单位
        
        Returns:
            订单ID
        """
        try:
            params = {
                "instId": symbol,
                "tdMode": settings.trading_mode,
                "side": side,
                "ordType": "market",
                "sz": str(size)
            }
            
            # 现货市价买入时，指定使用计价货币(USDT)作为数量
            if side == "buy" and use_quote_ccy:
                params["tgtCcy"] = "quote_ccy"
            
            response = self.trade_api.place_order(**params)
            
            if response['code'] != '0':
                logger.error(f"Failed to place market order: {response['msg']}, response: {response}")
                return None
            
            order_id = response['data'][0]['ordId']
            logger.info(f"Market order placed: {side} {symbol} {size}, ordId={order_id}")
            return order_id
            
        except Exception as e:
            logger.error(f"Error placing market order: {e}")
            return None
    
    def get_order_status(self, symbol: str, order_id: str) -> Optional[Dict]:
        """
        查询订单状态
        
        Returns:
            订单信息字典,包含state字段: 
            - live: 未成交
            - partially_filled: 部分成交
            - filled: 完全成交
            - canceled: 已撤销
        """
        try:
            response = self.trade_api.get_order(
                instId=symbol,
                ordId=order_id
            )
            
            if response['code'] != '0' or not response['data']:
                logger.error(f"Failed to get order status: {response.get('msg', 'No data')}")
                return None
            
            order_data = response['data'][0]
            
            # 安全转换浮点数，处理空字符串情况
            def safe_float(value, default=0.0):
                if value == '' or value is None:
                    return default
                try:
                    return float(value)
                except (ValueError, TypeError):
                    return default
            
            return {
                'ordId': order_data['ordId'],
                'state': order_data['state'],
                'avgPx': safe_float(order_data.get('avgPx')),  # 成交均价
                'accFillSz': safe_float(order_data.get('accFillSz')),  # 累计成交数量
                'sz': safe_float(order_data.get('sz'))  # 订单数量
            }
            
        except Exception as e:
            logger.error(f"Error getting order status: {e}")
            return None
    
    def cancel_order(self, symbol: str, order_id: str) -> bool:
        """撤单"""
        try:
            response = self.trade_api.cancel_order(
                instId=symbol,
                ordId=order_id
            )
            
            if response['code'] != '0':
                logger.error(f"Failed to cancel order: {response['msg']}")
                return False
            
            logger.info(f"Order cancelled: {order_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error cancelling order: {e}")
            return False
    
    def place_stop_loss_order(self, symbol: str, trigger_price: float, size: float) -> Optional[str]:
        """
        下止损条件单（触发后市价卖出）
        
        Args:
            symbol: 交易对
            trigger_price: 触发价格
            size: 数量
        
        Returns:
            订单ID
        """
        try:
            response = self.trade_api.place_algo_order(
                instId=symbol,
                tdMode=settings.trading_mode,
                side="sell",
                ordType="conditional",
                sz=str(size),
                triggerPx=str(trigger_price),
                orderPx="-1"  # -1表示市价
            )
            
            if response['code'] != '0':
                logger.error(f"Failed to place stop loss order: {response['msg']}")
                return None
            
            order_id = response['data'][0]['algoId']
            logger.info(f"Stop loss order placed: trigger={trigger_price}, algoId={order_id}")
            return order_id
            
        except Exception as e:
            logger.error(f"Error placing stop loss order: {e}")
            return None
    
    def place_take_profit_order(self, symbol: str, trigger_price: float, size: float) -> Optional[str]:
        """
        下止盈条件单（触发后市价卖出）
        
        Args:
            symbol: 交易对
            trigger_price: 触发价格
            size: 数量
        
        Returns:
            订单ID
        """
        try:
            response = self.trade_api.place_algo_order(
                instId=symbol,
                tdMode=settings.trading_mode,
                side="sell",
                ordType="conditional",
                sz=str(size),
                triggerPx=str(trigger_price),
                orderPx="-1"  # -1表示市价
            )
            
            if response['code'] != '0':
                logger.error(f"Failed to place take profit order: {response['msg']}")
                return None
            
            order_id = response['data'][0]['algoId']
            logger.info(f"Take profit order placed: trigger={trigger_price}, algoId={order_id}")
            return order_id
            
        except Exception as e:
            logger.error(f"Error placing take profit order: {e}")
            return None
    
    def cancel_algo_order(self, symbol: str, algo_id: str) -> bool:
        """撤销条件单"""
        try:
            response = self.trade_api.cancel_algo_order([{
                "instId": symbol,
                "algoId": algo_id
            }])
            
            if response['code'] != '0':
                logger.error(f"Failed to cancel algo order: {response['msg']}")
                return False
            
            logger.info(f"Algo order cancelled: {algo_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error cancelling algo order: {e}")
            return False
    
    def close_position(self, symbol: str) -> bool:
        """平仓(市价) - 现货模式卖出全部基础货币，合约模式平仓"""
        try:
            position = self.get_position(symbol)
            
            if not position.has_position:
                logger.warning("No position to close")
                return True
            
            # 现货交易模式：卖出全部基础货币
            if settings.trading_mode == "cash":
                base_currency = symbol.split('-')[0]
                
                # 获取基础货币余额
                balance_response = self.account_api.get_account_balance(ccy=base_currency)
                if balance_response['code'] != '0' or not balance_response['data']:
                    logger.error("Failed to get balance for closing position")
                    return False
                
                # 查找基础货币余额
                pos_size = 0.0
                for detail in balance_response['data'][0]['details']:
                    if detail['ccy'] == base_currency:
                        pos_size = float(detail.get('availBal', 0))
                        break
                
                if pos_size < 0.0001:
                    logger.warning("No balance to sell")
                    return True
                
                # 获取当前价格，检查订单金额
                current_price = self.get_current_price(symbol)
                if not current_price:
                    logger.error("Failed to get current price for closing position")
                    return False
                
                order_value = pos_size * current_price
                min_order_value = 5.0  # OKX现货最小订单金额通常为5 USDT
                
                logger.info(f"准备平仓: {pos_size} {base_currency} @ {current_price} = {order_value:.2f} USDT")
                
                # 检查订单金额是否满足最小要求
                if order_value < min_order_value:
                    logger.warning(f"⚠️ 订单金额 {order_value:.2f} USDT 小于最小要求 {min_order_value} USDT，无法平仓")
                    logger.warning(f"建议：等待价格上涨或手动处理小额持仓")
                    return False
                
                # 市价卖出全部
                order_id = self.place_market_order(symbol, "sell", pos_size)
                
                if order_id:
                    logger.info(f"Position closed: sold {pos_size} {base_currency}")
                    return True
                
                return False
            
            # 合约交易模式：使用持仓API
            else:
                response = self.account_api.get_positions(instId=symbol)
                if response['code'] != '0' or not response['data']:
                    return False
                
                pos_data = response['data'][0]
                pos_size = abs(float(pos_data.get('pos', 0)))
                
                side = "sell" if float(pos_data.get('pos', 0)) > 0 else "buy"
                
                order_id = self.place_market_order(symbol, side, pos_size)
                
                if order_id:
                    logger.info(f"Position closed: {symbol}")
                    return True
                
                return False
            
        except Exception as e:
            logger.error(f"Error closing position: {e}")
            return False
