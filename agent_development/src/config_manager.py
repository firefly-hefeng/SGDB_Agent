import yaml
from pathlib import Path
from typing import Any, Dict, Optional
import os

class ConfigManager:
    """配置文件管理器"""
    
    def __init__(self, config_path: str = "config/config.yaml"):
        self.config_path = Path(config_path)
        self.config = self._load_config()
        self._process_env_vars()
    
    def _load_config(self) -> Dict[str, Any]:
        """加载配置文件"""
        if not self.config_path.exists():
            raise FileNotFoundError(f"配置文件不存在: {self.config_path}")
        
        with open(self.config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        return config or {}
    
    def _process_env_vars(self):
        """
        使用环境变量覆盖配置文件中的敏感信息
        """

        # 覆盖 primary LLM API Key
        primary_key = os.getenv('PRIMARY_LLM_API_KEY') or os.getenv('KIMI_API_KEY')
        if primary_key:
            self.config.setdefault('ai', {})
            self.config['ai'].setdefault('primary', {})
            self.config['ai']['primary']['api_key'] = primary_key

        # 覆盖 fallback LLM API Key
        fallback_key = os.getenv('FALLBACK_LLM_API_KEY') or os.getenv('CLAUDE_API_KEY')
        if fallback_key:
            self.config.setdefault('ai', {})
            self.config['ai'].setdefault('fallback', {})
            self.config['ai']['fallback']['api_key'] = fallback_key
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        获取配置值，支持点号分隔的嵌套键
        
        Args:
            key: 配置键，支持 'section.subsection.key' 格式
            default: 默认值
        
        Returns:
            配置值
        """
        keys = key.split('.')
        value = self.config
        
        try:
            for k in keys:
                value = value[k]
            return value
        except (KeyError, TypeError):
            return default
    
    def set(self, key: str, value: Any):
        """
        设置配置值
        
        Args:
            key: 配置键，支持 'section.subsection.key' 格式
            value: 配置值
        """
        keys = key.split('.')
        config = self.config
        
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
        
        config[keys[-1]] = value
    
    def save(self):
        """保存配置到文件"""
        with open(self.config_path, 'w', encoding='utf-8') as f:
            yaml.safe_dump(self.config, f, allow_unicode=True, default_flow_style=False)
    
    def __getitem__(self, key: str) -> Any:
        """支持字典式访问"""
        return self.get(key)
    
    def __setitem__(self, key: str, value: Any):
        """支持字典式设置"""
        self.set(key, value)