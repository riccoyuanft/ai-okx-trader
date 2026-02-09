"""DingTalk notification service"""

import requests
import hmac
import hashlib
import base64
import time
from typing import Optional
from loguru import logger


class DingTalkNotifier:
    """钉钉机器人通知服务"""
    
    def __init__(self, webhook_url: str, secret: Optional[str] = None):
        """
        初始化钉钉通知器
        
        Args:
            webhook_url: 钉钉机器人webhook地址
            secret: 钉钉机器人加签密钥（可选）
        """
        self.webhook_url = webhook_url
        self.secret = secret
        self.enabled = bool(webhook_url)
        
        if self.enabled:
            logger.info(f"钉钉通知已启用 (加签: {'是' if secret else '否'})")
        else:
            logger.warning("钉钉通知未启用：未配置webhook_url")
    
    def _generate_sign(self) -> tuple[str, str]:
        """
        生成钉钉加签
        
        Returns:
            (timestamp, sign) 时间戳和签名
        """
        timestamp = str(round(time.time() * 1000))
        secret_enc = self.secret.encode('utf-8')
        string_to_sign = f'{timestamp}\n{self.secret}'
        string_to_sign_enc = string_to_sign.encode('utf-8')
        hmac_code = hmac.new(secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()
        sign = base64.b64encode(hmac_code).decode('utf-8')
        return timestamp, sign
    
    def send_text(self, content: str, at_all: bool = False) -> bool:
        """
        发送文本消息
        
        Args:
            content: 消息内容
            at_all: 是否@所有人
            
        Returns:
            是否发送成功
        """
        if not self.enabled:
            return False
        
        try:
            url = self.webhook_url
            
            if self.secret:
                timestamp, sign = self._generate_sign()
                url = f"{url}&timestamp={timestamp}&sign={sign}"
            
            data = {
                "msgtype": "text",
                "text": {
                    "content": content
                },
                "at": {
                    "isAtAll": at_all
                }
            }
            
            response = requests.post(url, json=data, timeout=5)
            result = response.json()
            
            if result.get("errcode") == 0:
                logger.debug(f"钉钉消息发送成功: {content[:50]}...")
                return True
            else:
                logger.error(f"钉钉消息发送失败: {result}")
                return False
                
        except Exception as e:
            logger.error(f"钉钉消息发送异常: {e}")
            return False
    
    def send_markdown(self, title: str, content: str, at_all: bool = False) -> bool:
        """
        发送Markdown消息
        
        Args:
            title: 消息标题
            content: Markdown格式内容
            at_all: 是否@所有人
            
        Returns:
            是否发送成功
        """
        if not self.enabled:
            return False
        
        try:
            url = self.webhook_url
            
            if self.secret:
                timestamp, sign = self._generate_sign()
                url = f"{url}&timestamp={timestamp}&sign={sign}"
            
            data = {
                "msgtype": "markdown",
                "markdown": {
                    "title": title + "[OKX]",
                    "text": content + "[OKX]"
                },
                "at": {
                    "isAtAll": at_all
                }
            }
            
            response = requests.post(url, json=data, timeout=5)
            result = response.json()
            
            if result.get("errcode") == 0:
                logger.debug(f"钉钉Markdown消息发送成功: {title}")
                return True
            else:
                logger.error(f"钉钉Markdown消息发送失败: {result}")
                return False
                
        except Exception as e:
            logger.error(f"钉钉Markdown消息发送异常: {e}")
            return False
    
    def notify_trade_signal(self, symbol: str, action: str, price: float, 
                           reason: str, stop_loss: Optional[float] = None, 
                           take_profit: Optional[list] = None) -> bool:
        """
        发送交易信号通知
        
        Args:
            symbol: 交易对
            action: 操作类型 (long/close/wait)
            price: 价格
            reason: 决策理由
            stop_loss: 止损价
            take_profit: 止盈价列表
            
        Returns:
            是否发送成功
        """
        action_emoji = {
            "long": "🚀",
            "close": "🔚",
            "wait": "⏸️"
        }
        
        action_text = {
            "long": "做多",
            "close": "平仓",
            "wait": "观望"
        }
        
        emoji = action_emoji.get(action, "📊")
        action_name = action_text.get(action, action)
        
        # 构建更具体的标题
        title = f"[{symbol}] {emoji} {action_name}信号"
        
        content = f"""### {emoji} AI交易信号
        
**交易对**: {symbol}  
**操作**: {action_name}  
**价格**: {price}  
**理由**: {reason}
"""
        
        if stop_loss:
            content += f"\n**止损**: {stop_loss}"
        
        if take_profit:
            tp_str = ", ".join([str(tp) for tp in take_profit])
            content += f"\n**止盈**: {tp_str}"
        
        content += f"\n\n> 时间: {time.strftime('%Y-%m-%d %H:%M:%S')}"
        
        return self.send_markdown(title, content)
    
    def notify_position_closed(self, symbol: str, entry_price: float, 
                              exit_price: float, pnl_pct: float, 
                              reason: str) -> bool:
        """
        发送平仓通知
        
        Args:
            symbol: 交易对
            entry_price: 入场价
            exit_price: 出场价
            pnl_pct: 盈亏百分比
            reason: 平仓原因
            
        Returns:
            是否发送成功
        """
        emoji = "✅" if pnl_pct > 0 else "❌"
        
        content = f"""### {emoji} 持仓已平仓
        
**交易对**: {symbol}  
**入场价**: {entry_price}  
**出场价**: {exit_price}  
**盈亏**: {pnl_pct:+.2f}%  
**原因**: {reason}

> 时间: {time.strftime('%Y-%m-%d %H:%M:%S')}
"""
        
        return self.send_markdown("持仓平仓通知", content, at_all=(abs(pnl_pct) > 5))
    
    def notify_stop_loss(self, symbol: str, price: float, 
                        entry_price: float, pnl_pct: float) -> bool:
        """
        发送止损通知
        
        Args:
            symbol: 交易对
            price: 止损价格
            entry_price: 入场价
            pnl_pct: 盈亏百分比
            
        Returns:
            是否发送成功
        """
        content = f"""### 🛑 止损触发
        
**交易对**: {symbol}  
**止损价**: {price}  
**入场价**: {entry_price}  
**盈亏**: {pnl_pct:+.2f}%

> 时间: {time.strftime('%Y-%m-%d %H:%M:%S')}
"""
        
        return self.send_markdown("止损触发", content, at_all=True)
    
    def notify_take_profit(self, symbol: str, price: float, 
                          entry_price: float, pnl_pct: float) -> bool:
        """
        发送止盈通知
        
        Args:
            symbol: 交易对
            price: 止盈价格
            entry_price: 入场价
            pnl_pct: 盈亏百分比
            
        Returns:
            是否发送成功
        """
        content = f"""### 🎯 止盈触发
        
**交易对**: {symbol}  
**止盈价**: {price}  
**入场价**: {entry_price}  
**盈亏**: {pnl_pct:+.2f}%

> 时间: {time.strftime('%Y-%m-%d %H:%M:%S')}
"""
        
        return self.send_markdown("止盈触发", content, at_all=True)
    
    def notify_risk_rejected(self, symbol: str, action: str, reason: str, 
                            risk_reason: str) -> bool:
        """
        发送风控拦截通知
        
        Args:
            symbol: 交易对
            action: 操作类型
            reason: AI决策理由
            risk_reason: 风控拦截原因
            
        Returns:
            是否发送成功
        """
        action_text = {
            "long": "做多",
            "close": "平仓",
        }
        
        action_name = action_text.get(action, action)
        
        content = f"""### 🛡️ 风控拦截
        
**交易对**: {symbol}  
**信号**: {action_name}  
**AI理由**: {reason}  
**拦截原因**: {risk_reason}

> ⚠️ 交易未执行，资金安全  
> 时间: {time.strftime('%Y-%m-%d %H:%M:%S')}
"""
        
        return self.send_markdown(f"[{symbol}] 🛡️ 风控拦截", content)
    
    def notify_trade_executed(self, symbol: str, action: str, price: float,
                             size: float, reason: str, 
                             stop_loss: Optional[float] = None,
                             take_profit: Optional[list] = None) -> bool:
        """
        发送交易执行成功通知
        
        Args:
            symbol: 交易对
            action: 操作类型 (long/close)
            price: 执行价格
            size: 仓位大小(%)
            reason: 决策理由
            stop_loss: 止损价
            take_profit: 止盈价列表
            
        Returns:
            是否发送成功
        """
        action_emoji = {
            "long": "✅",
            "close": "✅"
        }
        
        action_text = {
            "long": "已买入",
            "close": "已卖出"
        }
        
        emoji = action_emoji.get(action, "✅")
        action_name = action_text.get(action, action)
        
        title = f"[{symbol}] {emoji} {action_name}"
        
        content = f"""### {emoji} 交易执行成功
        
**交易对**: {symbol}  
**操作**: {action_name}  
**价格**: {price}  
**仓位**: {size}%  
**理由**: {reason}
"""
        
        if stop_loss:
            content += f"\n**止损**: {stop_loss}"
        
        if take_profit:
            tp_str = ", ".join([str(tp) for tp in take_profit])
            content += f"\n**止盈**: {tp_str}"
        
        content += f"\n\n> ✅ 交易已执行  \n> 时间: {time.strftime('%Y-%m-%d %H:%M:%S')}"
        
        return self.send_markdown(title, content, at_all=True)
    
    def notify_error(self, error_msg: str) -> bool:
        """
        发送错误通知
        
        Args:
            error_msg: 错误信息
            
        Returns:
            是否发送成功
        """
        content = f"""### ⚠️ 系统错误
        
**错误信息**: {error_msg}

> 时间: {time.strftime('%Y-%m-%d %H:%M:%S')}
"""
        
        return self.send_markdown("系统错误", content, at_all=True)
