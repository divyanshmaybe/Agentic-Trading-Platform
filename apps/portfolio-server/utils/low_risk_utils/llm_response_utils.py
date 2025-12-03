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

    # Step 2.5: Check for empty response
    if not response_text or not response_text.strip():
        logger.error("Empty response text received from LLM")
        raise json.JSONDecodeError(
            "Invalid JSON in LLM response: Empty response",
            response_text,
            0
        )

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

    # Handle content that is a list of content blocks (Gemini format)
    # e.g., [{'type': 'text', 'text': '...'}]
    if isinstance(content, list) and len(content) > 0:
        # Extract text from content blocks
        text_parts = []
        for block in content:
            if isinstance(block, dict):
                if 'text' in block:
                    text_parts.append(block['text'])
                elif 'content' in block:
                    text_parts.append(block['content'])
            else:
                text_parts.append(str(block))
        content = '\n'.join(text_parts)

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


def extract_structured_field(
    text: str, 
    field_name: str, 
    field_type: type = str,
    patterns: List[str] = None
) -> Any:
    """
    Extract a specific field from structured LLM response text.
    
    Handles common formats like:
    - field_name: value
    - field_name : value
    - "field_name": value
    
    Args:
        text: Response text to parse
        field_name: Name of the field to extract (e.g., "trading_signal")
        field_type: Expected type of the value (int, float, str)
        patterns: Optional custom regex patterns (group 1 should capture the value)
        
    Returns:
        Extracted value converted to field_type, or None if not found
    """
    if not isinstance(text, str) or not text.strip():
        return None
    
    # Default patterns for common field formats
    if patterns is None:
        patterns = [
            rf'{field_name}:\s*(-?\d+\.?\d*)',  # field: value (numbers)
            rf'{field_name}\s*:\s*(-?\d+\.?\d*)',  # field : value
            rf'"{field_name}":\s*(-?\d+\.?\d*)',  # "field": value (JSON-like)
            rf'{field_name}:\s*"?([^"\n]+)"?',  # field: "value" or field: value (strings)
        ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            value_str = match.group(1).strip()
            try:
                if field_type == int:
                    return int(float(value_str))  # Handle "1.0" -> 1
                elif field_type == float:
                    return float(value_str)
                else:
                    return value_str
            except (ValueError, TypeError) as e:
                logger.warning(f"Failed to convert '{value_str}' to {field_type}: {e}")
                continue
    
    return None


def extract_trading_signal_fields(text: str) -> Dict[str, Any]:
    """
    Extract trading signal fields from structured LLM response.
    
    Extracts:
    - trading_signal: int (-1, 0, 1)
    - confidence_score: float (0.0 to 1.0)
    - explanation / concise_explanation: str
    - final_signal: int (if present, from validation model)
    
    Args:
        text: Structured response text from LLM
        
    Returns:
        Dictionary with extracted fields, defaults for missing values
    """
    # Clean the response first
    cleaned = clean_markdown_from_response(text)
    
    result = {
        "trading_signal": 0,
        "confidence_score": 0.5,
        "explanation": "",
        "final_signal": None,
    }
    
    # Extract trading_signal (try multiple patterns)
    signal_patterns = [
        r"trading_signal:\s*(-?\d+)",
        r"signal:\s*(-?\d+)",
        r"final_signal:\s*(-?\d+)",
    ]
    for pattern in signal_patterns:
        match = re.search(pattern, cleaned, re.IGNORECASE)
        if match:
            try:
                signal = int(match.group(1))
                if signal in [-1, 0, 1]:
                    result["trading_signal"] = signal
                    break
            except ValueError:
                continue
    
    # Extract final_signal specifically (may differ from trading_signal)
    final_match = re.search(r"final_signal:\s*(-?\d+)", cleaned, re.IGNORECASE)
    if final_match:
        try:
            result["final_signal"] = int(final_match.group(1))
        except ValueError:
            pass
    
    # Extract confidence_score
    conf_patterns = [
        r"confidence_score:\s*([0-9]*\.?[0-9]+)",
        r"confidence:\s*([0-9]*\.?[0-9]+)",
    ]
    for pattern in conf_patterns:
        match = re.search(pattern, cleaned, re.IGNORECASE)
        if match:
            try:
                conf = float(match.group(1))
                result["confidence_score"] = max(0.0, min(1.0, conf))  # Clamp to [0, 1]
                break
            except ValueError:
                continue
    
    # Extract explanation
    exp_patterns = [
        r"concise_explanation:\s*(.*?)(?:\n__|$)",
        r"explanation:\s*(.*?)(?:\n__|$)",
    ]
    for pattern in exp_patterns:
        match = re.search(pattern, cleaned, re.DOTALL | re.IGNORECASE)
        if match:
            explanation = match.group(1).strip()
            # Clean up any trailing markers
            explanation = re.sub(r'\n__LLM_TIMING__.*$', '', explanation).strip()
            if explanation:
                result["explanation"] = explanation
                break
    
    return result
