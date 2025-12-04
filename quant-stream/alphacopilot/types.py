"""
Data type definitions for LangGraph AlphaCopilot workflow.

This module contains:
- Dataclasses for workflow entities (Hypothesis, Experiment, Trace, etc.)
- TypedDict for LangGraph state management (WorkflowState)

These types mirror the structure used in alphacopilot but are completely independent.
No imports from alphacopilot package.
"""

from dataclasses import dataclass, field
from typing import Any, Optional, Sequence, TypedDict, List, Dict, Annotated
from operator import add


@dataclass
class Hypothesis:
    """Market hypothesis that guides factor creation.

    Reference: alphacopilot/core/proposal.py - Hypothesis class (lines 21-54)
    """
    hypothesis: str  # The hypothesis statement
    reason: str  # Detailed reasoning
    concise_reason: str  # Concise reasoning
    concise_observation: str  # Observations
    concise_justification: str  # Justification
    concise_knowledge: str  # Transferable knowledge


@dataclass
class FactorTask:
    """Individual factor task within an experiment.

    Reference: alphacopilot/core/experiment.py - Task class (lines 20-35)
    """
    name: str  # Factor name
    description: str  # Factor description
    expression: str  # Factor expression (code)
    formulation: str  # LaTeX formula
    variables: dict[str, str]  # Variable descriptions


@dataclass
class FBWorkspace:
    """File-based workspace for task implementation.

    Reference: alphacopilot/core/experiment.py - FBWorkspace class (lines 70-189)
    """
    workspace_path: str  # Path to workspace directory
    code_dict: dict[str, str]  # Dictionary of file_name -> code content
    target_task: Optional[FactorTask] = None  # Associated task


@dataclass
class Experiment:
    """Experiment containing multiple factor tasks and their implementations.

    Reference: alphacopilot/core/experiment.py - Experiment class (lines 196-214)
    """
    sub_tasks: Sequence[FactorTask]  # List of factor tasks (2-3 factors)
    sub_workspace_list: list[Optional[FBWorkspace]] = field(default_factory=list)  # Workspaces for each task
    result: Any = None  # Backtest results object
    sub_results: dict[str, float] = field(default_factory=dict)  # Metrics per factor (e.g., annualized_return, sharpe_ratio)
    experiment_workspace: Optional[FBWorkspace] = None  # Main experiment workspace


@dataclass
class HypothesisFeedback:
    """Feedback on hypothesis evaluation and results.

    Reference: alphacopilot/core/proposal.py - HypothesisFeedback class (lines 60-83)
    """
    observations: str  # Observations on results
    hypothesis_evaluation: str  # Evaluation of hypothesis
    new_hypothesis: str  # Suggested new hypothesis direction
    reason: str  # Reasoning for feedback
    decision: bool  # Whether to replace current SOTA


@dataclass
class Trace:
    """Trace object for tracking workflow history.

    Reference: alphacopilot/core/proposal.py - Trace class (lines 90-103)
    """
    hist: list[tuple[Hypothesis, Experiment, HypothesisFeedback]] = field(default_factory=list)
    scen: Any = None  # Scenario object (can be None for standalone)
    knowledge_base: Any = None  # Knowledge base (can be None for standalone)

    def get_sota_hypothesis_and_experiment(self) -> tuple[Optional[Hypothesis], Optional[Experiment]]:
        """Get the best hypothesis and experiment based on feedback decisions."""
        for hypothesis, experiment, feedback in reversed(self.hist):
            if feedback.decision:
                return hypothesis, experiment
        return None, None


# ============================================================================
# LangGraph State Schema
# ============================================================================

class WorkflowStateRequired(TypedDict):
    """State schema for the AlphaCopilot workflow graph.

    This state is passed between nodes and updated at each step.
    Uses TypedDict for LangGraph state management.
    """
    trace: Trace  # History tracking object
    hypothesis: Optional[Hypothesis]  # Output from factor_propose
    experiment: Optional[Experiment]  # Updated at each step (factor_construct, factor_validate, factor_workflow)
    feedback: Optional[HypothesisFeedback]  # Output from feedback node
    potential_direction: Optional[str]  # Initial direction guidance (for first iteration)
    mcp_tools: List[Any]  # MCP tools loaded via langchain-mcp-adapters
    mcp_server: Optional[str]  # MCP server endpoint (when using MCP backend)
    workflow_config: Dict[str, Any]  # Workflow configuration (data, strategy, model, backtest)
    custom_factors: Optional[List[str]]  # User-provided custom factors (expressions) to merge with agent-generated ones

    # Loop control
    max_iterations: int  # Maximum number of iterations (default: 1)
    stop_on_sota: bool  # Stop early if SOTA is found (default: False)
    # Agent logs: append-only list of short run logs. Uses langgraph reducer `add_messages`
    agent_logs: Annotated[list[str], add]
    validation_error: bool

class WorkflowState(WorkflowStateRequired, total=False):
    # MLflow integration
    recorder: Any
    mlflow_context: Any
    _mlflow_llm_step: int
    _mlflow_iteration: int


