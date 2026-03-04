"""Strategy configuration loader"""

import yaml
from pathlib import Path
from typing import Dict, Any
from src.config.settings import settings


class StrategyLoader:
    """Load and manage strategy configurations from YAML files"""
    
    def __init__(self, strategy_name: str = None):
        """
        Initialize strategy loader
        
        Args:
            strategy_name: Name of the strategy file (without .yaml extension)
                          If None, will use STRATEGY_NAME from .env
        """
        self.strategy_name = strategy_name or getattr(settings, 'strategy_name', '15m_trend_following')
        self.strategies_dir = Path(__file__).parent.parent.parent / 'strategies'
        self.strategy_config = self._load_strategy()
    
    def _load_strategy(self) -> Dict[str, Any]:
        """Load strategy configuration from YAML file"""
        strategy_file = self.strategies_dir / f"{self.strategy_name}.yaml"
        
        if not strategy_file.exists():
            raise FileNotFoundError(
                f"Strategy file not found: {strategy_file}\n"
                f"Available strategies: {self.list_available_strategies()}"
            )
        
        with open(strategy_file, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        return config
    
    def list_available_strategies(self) -> list:
        """List all available strategy files"""
        if not self.strategies_dir.exists():
            return []
        
        return [f.stem for f in self.strategies_dir.glob('*.yaml')]
    
    def get_parameters(self) -> Dict[str, Any]:
        """Get strategy parameters"""
        return self.strategy_config.get('parameters', {})
    
    def get_description(self) -> str:
        """Get strategy description"""
        return self.strategy_config.get('description', '').strip()
    
    def get_core_principles(self) -> str:
        """Get core principles section"""
        return self.strategy_config.get('core_principles', '').strip()
    
    def get_strict_constraints(self) -> str:
        """Get strict constraints section"""
        return self.strategy_config.get('strict_constraints', '').strip()
    
    def get_output_format(self) -> str:
        """Get output format section"""
        return self.strategy_config.get('output_format', '').strip()
    
    def format_prompt(self, **runtime_vars) -> str:
        """
        Format the complete strategy prompt with runtime variables
        
        Args:
            **runtime_vars: Runtime variables to inject (e.g., symbol, initial_capital)
        
        Returns:
            Formatted strategy prompt string
        """
        # Merge strategy parameters with runtime variables
        params = self.get_parameters().copy()
        
        # Runtime variables from .env override strategy defaults
        if 'symbol' in runtime_vars:
            params['symbol'] = runtime_vars['symbol']
        if 'initial_capital' in runtime_vars:
            params['initial_capital'] = runtime_vars['initial_capital']
        if 'max_daily_risk_pct' in runtime_vars:
            params['max_daily_risk_pct'] = runtime_vars['max_daily_risk_pct']
        
        # Format all sections with parameters
        description = self._format_text(self.get_description(), params)
        core_principles = self._format_text(self.get_core_principles(), params)
        strict_constraints = self._format_text(self.get_strict_constraints(), params)
        output_format = self._format_text(self.get_output_format(), params)
        
        # Combine all sections
        prompt_parts = []
        if description:
            prompt_parts.append(description)
        if core_principles:
            prompt_parts.append(core_principles)
        if strict_constraints:
            prompt_parts.append(strict_constraints)
        if output_format:
            prompt_parts.append(output_format)
        
        return '\n\n'.join(prompt_parts)
    
    def _format_text(self, text: str, params: Dict[str, Any]) -> str:
        """
        Format text with parameters using {variable} syntax
        
        Args:
            text: Text to format
            params: Parameters dictionary
        
        Returns:
            Formatted text
        """
        if not text:
            return ""
        
        try:
            return text.format(**params)
        except KeyError as e:
            raise ValueError(
                f"Missing parameter in strategy template: {e}\n"
                f"Available parameters: {list(params.keys())}"
            )


# Global strategy loader instance (lazy loaded)
_strategy_loader = None


def get_strategy_loader(strategy_name: str = None) -> StrategyLoader:
    """
    Get or create the global strategy loader instance
    
    Args:
        strategy_name: Strategy name to load (if creating new instance)
    
    Returns:
        StrategyLoader instance
    """
    global _strategy_loader
    
    # If strategy_name is provided and different from current, reload
    if strategy_name and (_strategy_loader is None or _strategy_loader.strategy_name != strategy_name):
        _strategy_loader = StrategyLoader(strategy_name)
    elif _strategy_loader is None:
        _strategy_loader = StrategyLoader()
    
    return _strategy_loader
