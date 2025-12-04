"""Server configuration."""

from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field
import yaml


class ServerConfig(BaseModel):
    """Server configuration."""
    
    host: str = Field("0.0.0.0", description="Server host")
    port: int = Field(8080, description="Server port")
    workers: int = Field(4, description="Number of worker processes")
    reload: bool = Field(False, description="Auto-reload on code changes")
    log_level: str = Field("INFO", description="Logging level")


class QuantStreamConfig(BaseModel):
    """Quant-stream specific configuration."""
    
    data_path: str = Field(".data/indian_stock_market_nifty500.csv", description="Default data path")
    mlruns_path: str = Field("sqlite:///mlruns.db", description="MLflow tracking URI")
    max_workers: int = Field(4, description="Max concurrent workflow runs")


class RedisConfig(BaseModel):
    """Redis configuration for Celery broker."""
    
    host: str = Field("localhost", description="Redis host")
    port: int = Field(6379, description="Redis port")
    db: int = Field(0, description="Redis database number")
    password: Optional[str] = Field(None, description="Redis password")
    
    @property
    def url(self) -> str:
        """Get Redis URL for Celery."""
        if self.password:
            return f"redis://:{self.password}@{self.host}:{self.port}/{self.db}"
        return f"redis://{self.host}:{self.port}/{self.db}"


class Config(BaseModel):
    """Complete server configuration."""
    
    server: ServerConfig = Field(default_factory=ServerConfig)
    quantstream: QuantStreamConfig = Field(default_factory=QuantStreamConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    
    @classmethod
    def from_yaml(cls, path: Path) -> "Config":
        """Load configuration from YAML file.
        
        Args:
            path: Path to YAML config file
            
        Returns:
            Config object
        """
        import yaml
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls(**data)
    
    @classmethod
    def from_env(cls) -> "Config":
        """Load configuration from environment variables.
        
        Returns:
            Config object with environment overrides
        """
        import os
        
        config = cls()
        
        # Server config
        if host := os.getenv("MCP_HOST"):
            config.server.host = host
        if port := os.getenv("MCP_PORT"):
            config.server.port = int(port)
        if workers := os.getenv("MCP_WORKERS"):
            config.server.workers = int(workers)
        if log_level := os.getenv("MCP_LOG_LEVEL"):
            config.server.log_level = log_level
        
        # Quant-stream config
        if data_path := os.getenv("QUANTSTREAM_DATA_PATH"):
            config.quantstream.data_path = data_path
        if mlruns_path := os.getenv("QUANTSTREAM_MLRUNS_PATH"):
            config.quantstream.mlruns_path = mlruns_path
        
        # Redis config
        if redis_host := os.getenv("REDIS_HOST"):
            config.redis.host = redis_host
        if redis_port := os.getenv("REDIS_PORT"):
            config.redis.port = int(redis_port)
        if redis_db := os.getenv("REDIS_DB"):
            config.redis.db = int(redis_db)
        if redis_password := os.getenv("REDIS_PASSWORD"):
            config.redis.password = redis_password
        
        return config


# Global config instance
_config: Optional[Config] = None


def get_config() -> Config:
    """Get global configuration instance.
    
    Returns:
        Config object
    """
    global _config
    if _config is None:
        # Try to load from config.yaml, otherwise use environment/defaults
        import os
        config_path = Path(__file__).parent / "config.yaml"
        if config_path.exists():
            _config = Config.from_yaml(config_path)
        else:
            _config = Config.from_env()
    return _config


def set_config(config: Config) -> None:
    """Set global configuration instance.
    
    Args:
        config: Config object to use
    """
    global _config
    _config = config

