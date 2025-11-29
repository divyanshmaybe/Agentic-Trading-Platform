"""
Prompt utility functions for loading and rendering templates.

Common utilities for managing YAML-based prompt templates used by
LLM agents across different pipelines.
"""

import logging
from pathlib import Path
from typing import Dict, Any

import yaml
from jinja2 import Environment, StrictUndefined


logger = logging.getLogger(__name__)


def load_prompt_from_template(template_name: str, template_dir: str = None) -> str:
    """
    Load a prompt template from YAML file.

    Args:
        template_name: Name of the template file (with or without .yaml extension)
        template_dir: Directory containing templates (if None, uses default templates/ dir)

    Returns:
        Prompt template string

    Raises:
        FileNotFoundError: If template file not found
        ValueError: If prompt is empty in template
    """
    # Handle template name with or without .yaml extension
    if not template_name.endswith('.yaml'):
        template_name = f"{template_name}.yaml"

    # Get template directory
    if template_dir is None:
        # Default: go up from utils/low_risk_utils to apps/portfolio-server/templates
        template_dir = Path(__file__).resolve().parent.parent.parent / "templates"
    else:
        template_dir = Path(template_dir)

    template_file = template_dir / template_name

    if not template_file.exists():
        raise FileNotFoundError(
            f"Prompt template not found at {template_file}\n"
            f"Available templates: {list(template_dir.glob('*.yaml'))}"
        )

    with open(template_file, "r") as f:
        template_data = yaml.safe_load(f)

    prompt = template_data.get("prompt", "")
    if not prompt:
        raise ValueError(f"Prompt template '{template_name}' is empty in YAML file")

    logger.info(f"✓ Loaded prompt template: {template_name}")
    return prompt


def render_prompt_template(template_string: str, **kwargs) -> str:
    """
    Render a Jinja2 template string with provided variables.

    Args:
        template_string: Jinja2 template string
        **kwargs: Variables to render in the template

    Returns:
        Rendered prompt string

    Raises:
        jinja2.exceptions.UndefinedError: If required variables are missing
    """
    try:
        env = Environment(undefined=StrictUndefined)
        template = env.from_string(template_string)
        rendered = template.render(**kwargs)
        logger.debug(f"✓ Rendered template with variables: {list(kwargs.keys())}")
        return rendered
    except Exception as e:
        logger.error(f"Failed to render template: {e}")
        logger.error(f"Template: {template_string[:200]}...")
        logger.error(f"Variables: {kwargs}")
        raise


def load_and_render_prompt(
    template_name: str,
    template_dir: str = None,
    **kwargs
) -> str:
    """
    Load a YAML template and render it with Jinja2 variables in one step.

    Args:
        template_name: Name of the template file (with or without .yaml extension)
        template_dir: Directory containing templates (if None, uses default)
        **kwargs: Variables to render in the template

    Returns:
        Rendered prompt string

    Raises:
        FileNotFoundError: If template file not found
        ValueError: If prompt is empty in template
        jinja2.exceptions.UndefinedError: If required variables are missing
    """
    template_string = load_prompt_from_template(template_name, template_dir)
    return render_prompt_template(template_string, **kwargs)
