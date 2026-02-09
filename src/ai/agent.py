"""AI decision agent using GPT-4o"""

import json
from typing import List, Dict
from datetime import datetime
from openai import OpenAI
from loguru import logger

from src.config.settings import settings
from src.config.prompts import get_system_prompt, format_market_data_message
from src.data.models import MarketData, AIDecision


class AIAgent:
    """AI决策代理"""
    
    def __init__(self):
        # 根据配置选择AI提供商
        if settings.ai_provider == "qwen":
            self.client = OpenAI(
                api_key=settings.qwen_api_key,
                base_url=settings.qwen_base_url
            )
            self.model = settings.qwen_model
            logger.info(f"AI Agent initialized (通义千问 {self.model})")
        elif settings.ai_provider == "doubao":
            self.client = OpenAI(
                api_key=settings.doubao_api_key,
                base_url=settings.doubao_base_url
            )
            self.model = settings.doubao_model
            logger.info(f"AI Agent initialized (豆包 {self.model})")
        else:
            self.client = OpenAI(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url
            )
            self.model = settings.openai_model
            logger.info(f"AI Agent initialized (OpenAI {self.model})")
        
        self.history: List[Dict] = []
        self.max_history = 10  # 优化：减少对话历史，提高效率
        
    
    def make_decision(self, market_data: MarketData) -> AIDecision:
        """
        基于市场数据做出交易决策
        
        Args:
            market_data: 市场数据
        
        Returns:
            AI决策
        """
        try:
            messages = self._build_messages(market_data)
            
            # 📝 打印发送给AI的最新消息
            logger.info("\n" + "="*60)
            logger.info("📤 发送给AI的消息:")
            logger.info("-"*60)
            latest_user_msg = messages[-1]["content"]
            # 如果消息太长，只显示前2000字符
            if len(latest_user_msg) > 2000:
                logger.info(latest_user_msg[:2000] + "\n... (消息过长，已截断)")
            else:
                logger.info(latest_user_msg)
            logger.info("-"*60)
            logger.info(f"历史消息数: {len(messages)-1} (不含本次)")
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0.7,
                max_tokens=500
            )
            
            decision_text = response.choices[0].message.content
            
            # 📝 打印AI的响应
            logger.info("\n📥 AI的响应:")
            logger.info("-"*60)
            logger.info(decision_text)
            logger.info("="*60 + "\n")
            
            decision = self._parse_decision(decision_text)
            
            self._update_history(market_data, decision)
            
            return decision
            
        except Exception as e:
            logger.error(f"Error making decision: {e}")
            return AIDecision(d="wait", r=f"Error: {str(e)}")
    
    def _build_messages(self, market_data: MarketData) -> List[Dict]:
        """构建消息列表"""
        # 动态生成系统提示词，适配多标的轮动
        system_prompt = get_system_prompt(symbol=market_data.symbol)
        messages = [{"role": "system", "content": system_prompt}]
        
        # 添加最近的对话历史
        messages.extend(self.history[-self.max_history:])
        
        user_message = format_market_data_message(market_data.model_dump())
        messages.append({"role": "user", "content": user_message})
        
        return messages
    
    def _parse_decision(self, response_text: str) -> AIDecision:
        """解析AI响应为决策对象"""
        try:
            data = json.loads(response_text)
            return AIDecision(**data)
        except Exception as e:
            logger.error(f"Failed to parse decision: {e}")
            return AIDecision(d="wait", r="Parse error")
    
    def _update_history(self, market_data: MarketData, decision: AIDecision):
        """更新会话历史（带智能摘要）"""
        user_msg = format_market_data_message(market_data.model_dump())
        assistant_msg = decision.model_dump_json()
        
        self.history.append({"role": "user", "content": user_msg})
        self.history.append({"role": "assistant", "content": assistant_msg})
        
        # 当历史超过限制时，进行智能摘要
        if len(self.history) > self.max_history * 2:
            self.history = self._smart_summarize_history()
        
        logger.debug(f"History updated, total messages: {len(self.history)}")
    
    def _smart_summarize_history(self) -> List[Dict]:
        """
        智能摘要历史记录，保留关键决策点
        
        保留规则（激进优化）：
        1. 所有开仓(long)决策 - 永久保留
        2. 所有平仓(close)决策 - 永久保留
        3. 最近3条观望(wait)决策 - 保持市场感知
        
        Returns:
            摘要后的历史记录
        """
        key_decisions = []
        recent_waits = []
        
        # 遍历历史，提取关键决策
        for i in range(0, len(self.history), 2):
            if i + 1 >= len(self.history):
                break
            
            user_msg = self.history[i]
            assistant_msg = self.history[i + 1]
            
            try:
                decision_data = json.loads(assistant_msg["content"])
                decision_type = decision_data.get("d", "wait")
                
                # 保留所有开仓和平仓决策
                if decision_type in ["long", "close"]:
                    key_decisions.append((i, user_msg, assistant_msg))
                # 暂存观望决策
                elif decision_type == "wait":
                    recent_waits.append((i, user_msg, assistant_msg))
            except:
                # 解析失败，保留该消息
                key_decisions.append((i, user_msg, assistant_msg))
        
        # 只保留最近3条观望决策（激进优化）
        recent_waits = recent_waits[-3:]
        
        # 合并并按原始顺序排序
        all_kept = key_decisions + recent_waits
        all_kept.sort(key=lambda x: x[0])
        
        # 重建历史列表
        summarized = []
        for _, user_msg, assistant_msg in all_kept:
            summarized.append(user_msg)
            summarized.append(assistant_msg)
        
        logger.info(f"📝 历史摘要: 保留 {len(key_decisions)} 个关键决策 + {len(recent_waits)} 个最近观望 (总计{len(summarized)//2}对)")
        
        return summarized
    
    def clear_history(self):
        """清空历史"""
        self.history = []
        logger.info("History cleared")
    
    def save_history(self, filepath: str):
        """保存历史到文件"""
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(self.history, f, ensure_ascii=False, indent=2)
            logger.info(f"History saved to {filepath}")
        except Exception as e:
            logger.error(f"Failed to save history: {e}")
    
    def load_history(self, filepath: str):
        """从文件加载历史"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                self.history = json.load(f)
            logger.info(f"History loaded from {filepath}, {len(self.history)} messages")
        except FileNotFoundError:
            logger.warning(f"History file not found: {filepath}")
        except Exception as e:
            logger.error(f"Failed to load history: {e}")
    
