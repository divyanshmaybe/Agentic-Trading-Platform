"""YAML configuration loader with validation."""

from pathlib import Path
from typing import Dict, Any, Union
import yaml

from quant_stream.config.schema import WorkflowConfig
from quant_stream.config.defaults import get_default_config


def load_yaml(path: Union[str, Path]) -> Dict[str, Any]:
    """Load YAML file.
    
    Args:
        path: Path to YAML file
        
    Returns:
        Dictionary with YAML contents
        
    Raises:
        FileNotFoundError: If file doesn't exist
        yaml.YAMLError: If YAML is invalid
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path}")
    
    with open(path, "r") as f:
        try:
            config = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML file: {e}")
    
    if config is None:
        raise ValueError(f"Empty configuration file: {path}")
    
    return config


def merge_with_defaults(config: Dict[str, Any]) -> Dict[str, Any]:
    """Merge configuration with defaults.
    
    Only merges required fields and nested configs. Optional top-level keys
    (like 'model') are not merged if not present in user config.
    
    Args:
        config: User configuration
        
    Returns:
        Merged configuration
    """
    defaults = get_default_config()
    
    # List of optional top-level keys that should NOT be merged if missing
    # These keys should only be included if explicitly provided by the user
    OPTIONAL_TOP_LEVEL_KEYS = {'model'}
    
    # Deep merge
    def deep_merge(base: Dict, override: Dict) -> Dict:
        """Recursively merge two dictionaries."""
        result = base.copy()
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = deep_merge(result[key], value)
            else:
                result[key] = value
        return result
    
    # Remove optional keys from defaults if not present in user config
    filtered_defaults = {
        k: v for k, v in defaults.items()
        if k not in OPTIONAL_TOP_LEVEL_KEYS or k in config
    }
    
    return deep_merge(filtered_defaults, config)


def load_config(path: Union[str, Path], validate: bool = True) -> WorkflowConfig:
    """Load and validate workflow configuration from YAML file.
    
    Args:
        path: Path to YAML configuration file
        validate: Whether to validate configuration (default: True)
        
    Returns:
        Validated WorkflowConfig object
        
    Raises:
        FileNotFoundError: If file doesn't exist
        ValueError: If configuration is invalid
        
    Example:
        >>> config = load_config("workflow.yaml")
        >>> print(config.data.path)
    """
    # Load YAML
    config_dict = load_yaml(path)
    
    # Merge with defaults
    config_dict = merge_with_defaults(config_dict)
    
    # Validate and create config object
    if validate:
        try:
            config = WorkflowConfig(**config_dict)
        except Exception as e:
            raise ValueError(f"Invalid configuration: {e}")
    else:
        config = WorkflowConfig.model_construct(**config_dict)
    
    return config


def load_config_from_dict(config_dict: Dict[str, Any], validate: bool = True) -> WorkflowConfig:
    """Load and validate workflow configuration from dictionary.
    
    Args:
        config_dict: Configuration dictionary
        validate: Whether to validate configuration (default: True)
        
    Returns:
        Validated WorkflowConfig object
        
    Example:
        >>> config = load_config_from_dict({"data": {"path": "data.csv"}})
    """
    # Merge with defaults
    config_dict = merge_with_defaults(config_dict)
    
    # Validate and create config object
    if validate:
        try:
            config = WorkflowConfig(**config_dict)
        except Exception as e:
            raise ValueError(f"Invalid configuration: {e}")
    else:
        config = WorkflowConfig.model_construct(**config_dict)
    
    return config


def save_config(config: WorkflowConfig, path: Union[str, Path]) -> None:
    """Save configuration to YAML file.
    
    Args:
        config: WorkflowConfig object
        path: Output path
        
    Example:
        >>> save_config(config, "workflow.yaml")
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    
    config_dict = config.model_dump()
    
    with open(path, "w") as f:
        yaml.dump(config_dict, f, default_flow_style=False, sort_keys=False)
