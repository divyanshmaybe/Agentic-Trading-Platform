"""
LLM response cleaning and parsing utilities.

Common utilities for processing and cleaning responses from LLM agents,
including markdown removal, JSON extraction, and validation.
"""

import json
import logging
import re
from typing import Any, Dict, List, Union


logger = logging.getLogger(__name__)


def clean_markdown_from_response(response_text: str) -> str:
    """
    Remove markdown code block markers from LLM response.

    Removes ```python, ```json, and ``` markers that LLMs often
    include when generating code or structured output.

    Args:
        response_text: Raw response text from LLM

    Returns:
        Cleaned text with markdown removed
    """
    if not isinstance(response_text, str):
        return str(response_text)

    # Remove markdown code block markers
    cleaned = re.sub(r"```(?:python|json|yaml|xml|html)?\s*\n?", "", response_text)
    cleaned = re.sub(r"```\s*$", "", cleaned)
    cleaned = cleaned.strip()

    return cleaned


def extract_json_from_text(text: str) -> str:
    """
    Extract JSON from text that may contain additional content.

    Looks for JSON array [...] or object {...} patterns in the text
    and extracts the first valid JSON structure found.

    Args:
        text: Text potentially containing JSON

    Returns:
        Extracted JSON string, or original text if no JSON found
    """
    if not isinstance(text, str):
        return str(text)

    # Try to find JSON array first
    json_match = re.search(r"\[.*\]", text, re.DOTALL)
    if json_match:
        return json_match.group(0)

    # Try to find JSON object
    json_match = re.search(r"\{.*\}", text, re.DOTALL)
    if json_match:
        return json_match.group(0)

    # Return original text if no JSON found
    return text


def parse_json_response(
    response_text: str,
    expected_type: type = None,
    clean_markdown: bool = True,
    extract_json: bool = True
) -> Union[Dict, List, Any]:
    """
    Parse JSON from LLM response with cleaning and validation.

    Args:
        response_text: Raw response text from LLM
        expected_type: Expected type (dict, list, etc.) for validation
        clean_markdown: Whether to remove markdown code blocks
        extract_json: Whether to extract JSON from surrounding text

    Returns:
        Parsed JSON object (dict, list, etc.)

    Raises:
        json.JSONDecodeError: If JSON parsing fails
        ValueError: If parsed type doesn't match expected_type
    """
    if not isinstance(response_text, str):
        response_text = str(response_text)

    # Step 1: Clean markdown if requested
    if clean_markdown:
        response_text = clean_markdown_from_response(response_text)
        logger.debug(f"After markdown cleaning: {response_text[:100]}...")

    # Step 2: Extract JSON if requested
    if extract_json:
        response_text = extract_json_from_text(response_text)
        logger.debug(f"After JSON extraction: {response_text[:100]}...")

    # Step 3: Parse JSON
    try:
        parsed = json.loads(response_text)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON: {e}")
        logger.error(f"Text: {response_text[:500]}")
        raise json.JSONDecodeError(
            f"Invalid JSON in LLM response: {e}",
            response_text,
            e.pos
        )

    # Step 4: Validate type if expected_type provided
    if expected_type is not None and not isinstance(parsed, expected_type):
        raise ValueError(
            f"Expected {expected_type.__name__}, got {type(parsed).__name__}"
        )

    logger.info(f"✓ Successfully parsed JSON response ({type(parsed).__name__})")
    return parsed


def extract_message_content_from_agent_result(result: Dict[str, Any]) -> str:
    """
    Extract the content from an agent result's messages.

    Handles various agent result formats from langchain/langgraph.

    Args:
        result: Agent result dictionary (typically from agent.invoke())

    Returns:
        Content string from the last message

    Raises:
        ValueError: If messages not found or empty
    """
    messages = result.get("messages", [])
    if not messages:
        raise ValueError("Agent returned no messages")

    # Get the last message (agent response)
    last_message = messages[-1]

    # Extract content
    if hasattr(last_message, "content"):
        content = last_message.content
    elif isinstance(last_message, dict):
        content = last_message.get("content", str(last_message))
    else:
        content = str(last_message)

    return content


def clean_and_parse_agent_json_response(
    result: Dict[str, Any],
    expected_type: type = None
) -> Union[Dict, List, Any]:
    """
    Complete pipeline: extract content from agent result and parse as JSON.

    Combines extract_message_content_from_agent_result and parse_json_response
    for the common use case of getting JSON from an agent.

    Args:
        result: Agent result dictionary (from agent.invoke())
        expected_type: Expected type (dict, list, etc.) for validation

    Returns:
        Parsed JSON object

    Raises:
        ValueError: If messages not found or parsing fails
        json.JSONDecodeError: If JSON parsing fails
    """
    # Extract content from agent result
    content = extract_message_content_from_agent_result(result)

    # Parse as JSON
    return parse_json_response(
        content,
        expected_type=expected_type,
        clean_markdown=True,
        extract_json=True
    )


def validate_percentage_list(
    items: List[Dict[str, Any]],
    required_keys: List[str] = None,
    normalize: bool = True,
    tolerance: float = 1.0
) -> List[Dict[str, Any]]:
    """
    Validate and normalize a list of items with percentage allocations.

    Common validation for industry/stock allocation lists from LLM agents.

    Args:
        items: List of dictionaries with "percentage" key
        required_keys: List of required keys in each item (default: ["percentage"])
        normalize: Whether to normalize percentages to sum to 100
        tolerance: Tolerance for percentage sum validation (default: 1.0%)

    Returns:
        Validated (and possibly normalized) list of items

    Raises:
        ValueError: If validation fails
    """
    if not isinstance(items, list):
        raise ValueError(f"Expected list, got {type(items).__name__}")

    if not items:
        raise ValueError("Empty list provided")

    if required_keys is None:
        required_keys = ["percentage"]

    # Validate each item
    total_percentage = 0.0
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"Item {i} is not a dict: {type(item).__name__}")

        # Check required keys
        for key in required_keys:
            if key not in item:
                raise ValueError(f"Item {i} missing required key '{key}'")

        # Validate and convert percentage to float
        try:
            percentage = float(item["percentage"])
            item["percentage"] = percentage
            total_percentage += percentage
        except (ValueError, TypeError) as e:
            raise ValueError(f"Item {i} has invalid percentage value: {item['percentage']}")

    # Check if percentages sum to approximately 100
    if abs(total_percentage - 100.0) > tolerance:
        if normalize and total_percentage > 0:
            logger.warning(
                f"Percentages sum to {total_percentage:.2f}%, normalizing to 100%..."
            )
            # Normalize to 100%
            for item in items:
                item["percentage"] = (item["percentage"] / total_percentage) * 100.0
        else:
            raise ValueError(
                f"Percentages sum to {total_percentage:.2f}%, expected ~100% "
                f"(tolerance: ±{tolerance}%)"
            )

    logger.info(
        f"✓ Validated {len(items)} items, total allocation: "
        f"{sum(item['percentage'] for item in items):.2f}%"
    )

    return items
