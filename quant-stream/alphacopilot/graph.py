"""
LangGraph workflow graph construction for AlphaCopilot factor mining process.

This module contains only the graph infrastructure:
- Graph construction and configuration
- Node numbering constants
- Control flow logic (should_continue)
- Graph compilation
- LangSmith tracing integration

Node implementations are in the nodes/ package.
"""

from dotenv import load_dotenv
import os
from typing import Any

from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI

from .types import WorkflowState
from .recorder_utils import create_recorder_logger
from .nodes import (
    factor_propose,
    factor_construct,
    factor_validate,
    factor_workflow,
    feedback,
)

# Load environment variables from .env file
load_dotenv()

# ============================================================================
# Phoenix Tracing Configuration
# ============================================================================
# Initialize Phoenix tracing for AlphaCopilot workflow
try:
    from phoenix.otel import register
    
    collector_endpoint = os.getenv("COLLECTOR_ENDPOINT")
    if collector_endpoint:
        tracer_provider = register(
            project_name="alphacopilot-workflow",
            endpoint=collector_endpoint,
            auto_instrument=True
        )
        print(f"✅ Phoenix tracing initialized for AlphaCopilot workflow: {collector_endpoint}")
    else:
        print("⚠️ COLLECTOR_ENDPOINT not set, Phoenix tracing disabled for AlphaCopilot")
except ImportError:
    print("⚠️ Phoenix not installed, tracing disabled for AlphaCopilot")
except Exception as e:
    print(f"⚠️ Failed to initialize Phoenix tracing for AlphaCopilot: {e}")

# ============================================================================
# LangSmith Configuration (Optional - can run alongside Phoenix)
# ============================================================================
def is_langsmith_enabled() -> bool:
    """Check if LangSmith tracing is enabled."""
    tracing = os.getenv("LANGSMITH_TRACING", os.getenv("LANGCHAIN_TRACING_V2", "false"))
    api_key = os.getenv("LANGSMITH_API_KEY", os.getenv("LANGCHAIN_API_KEY", ""))
    return tracing.lower() == "true" and bool(api_key)

def get_langsmith_project() -> str:
    """Get the LangSmith project name."""
    return os.getenv("LANGSMITH_PROJECT", os.getenv("LANGCHAIN_PROJECT", "alphacopilot"))

# Log LangSmith status on module load
if is_langsmith_enabled():
    print(f"🔍 LangSmith tracing also enabled for project: {get_langsmith_project()}")
else:
    print("ℹ️ LangSmith tracing disabled. Set LANGSMITH_TRACING=true and LANGSMITH_API_KEY to enable.")

# Initialize LLM
llm = ChatOpenAI(
    base_url=os.getenv("LLM_BASE_URL"),
    api_key=os.getenv("LLM_API_KEY"),
    model=os.getenv("LLM_MODEL_NAME")
)

# ============================================================================
# Node Configuration
# ============================================================================

# Node numbering for organized logging
NODE_NUMBERS = {
    "factor_propose": "01",
    "factor_construct": "02",
    "factor_validate": "03",
    "factor_workflow": "04",
    "feedback": "05",
}

# ============================================================================
# Node Wrapper Functions
# ============================================================================

def _factor_propose(state: WorkflowState) -> dict[str, Any]:
    """Wrapper for factor_propose node."""
    return factor_propose(state, llm, NODE_NUMBERS["factor_propose"])


def _factor_construct(state: WorkflowState) -> dict[str, Any]:
    """Wrapper for factor_construct node."""
    return factor_construct(state, llm, NODE_NUMBERS["factor_construct"])


def _factor_validate(state: WorkflowState) -> dict[str, Any]:
    """Wrapper for factor_validate node."""
    return factor_validate(state, NODE_NUMBERS["factor_validate"])


def _factor_workflow(state: WorkflowState) -> dict[str, Any]:
    """Wrapper for factor_workflow node."""
    return factor_workflow(state, NODE_NUMBERS["factor_workflow"])


def _feedback(state: WorkflowState) -> dict[str, Any]:
    """Wrapper for feedback node."""
    return feedback(state, llm, NODE_NUMBERS["feedback"])


# ============================================================================
# Control Flow
# ============================================================================

def should_continue(state: WorkflowState) -> str:
    """
    Decide whether to continue iterating or stop.

    Stops if:
    - max_iterations reached
    - stop_on_sota=True and current iteration is SOTA
    - User manually sets a stop signal

    Returns:
        "continue" to loop back to factor_propose
        "end" to finish workflow
    """
    logger = create_recorder_logger(state.get("recorder"))
    trace = state.get("trace")

    # Check max iterations
    max_iterations = state.get("max_iterations", 1)  # Default: single iteration
    current_iteration = len(trace.hist)

    if current_iteration >= max_iterations:
        logger.info("\n" + "=" * 60)
        logger.info(f"✓ Reached max iterations ({max_iterations}), stopping workflow")
        logger.info("=" * 60)
        logger.flush()
        return "end"

    # Check if we should stop on SOTA
    stop_on_sota = state.get("stop_on_sota", False)
    if stop_on_sota and trace.hist:
        latest_feedback = trace.hist[-1][2]  # (hypothesis, experiment, feedback)
        if latest_feedback.decision:  # This is SOTA
            logger.info("\n" + "=" * 60)
            logger.info("✓ Found SOTA result and stop_on_sota=True, stopping workflow")
            logger.info("=" * 60)
            logger.flush()
            return "end"

    # Continue to next iteration
    logger.info("\n" + "=" * 60)
    logger.info(f"→ Continuing to iteration {current_iteration + 1}/{max_iterations}")
    logger.info("=" * 60 + "\n")
    logger.flush()
    return "continue"

def check_error(state: WorkflowState) -> str:
    error = state.get("validation_error", False)
    if error:
        return "construct"
    return "workflow"

# ============================================================================
# Graph Construction
# ============================================================================

def create_workflow_graph() -> StateGraph:
    """
    Create and configure the AlphaCopilot workflow graph.

    Graph Flow (with iteration loop):
        START → factor_propose → factor_construct → factor_validate →
        factor_workflow → feedback → [should_continue?]
                                          ↓ continue
                                    factor_propose (loop back)
                                          ↓ end
                                        END

    The workflow can iterate multiple times, controlled by:
    - max_iterations: Maximum number of iterations (default: 1)
    - stop_on_sota: Stop early if SOTA is found (default: False)
    """
    # Create the graph
    workflow = StateGraph(WorkflowState)

    # Add nodes (using wrapper functions that inject llm and node_number)
    workflow.add_node("factor_propose", _factor_propose)
    workflow.add_node("factor_construct", _factor_construct)
    workflow.add_node("factor_validate", _factor_validate)
    workflow.add_node("factor_workflow", _factor_workflow)
    workflow.add_node("feedback", _feedback)

    # Define edges (sequential flow with conditional loop)
    workflow.set_entry_point("factor_propose")
    workflow.add_edge("factor_propose", "factor_construct")
    workflow.add_edge("factor_construct", "factor_validate")
    workflow.add_conditional_edges(
        "factor_validate",
        check_error,
        {
            "construct": "factor_construct",
            "workflow": "factor_workflow"
        }
    )
    workflow.add_edge("factor_workflow", "feedback")

    # Conditional edge: loop back or end
    workflow.add_conditional_edges(
        "feedback",
        should_continue,
        {
            "continue": "factor_propose",  # Loop back for next iteration
            "end": END,                     # Finish workflow
        }
    )

    return workflow.compile()


