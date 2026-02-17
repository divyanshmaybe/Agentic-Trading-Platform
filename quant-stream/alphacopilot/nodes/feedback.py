"""
Feedback Node - Generate feedback on hypothesis and experiment results.

This module contains:
- Node function: feedback()
- Prompts: System and user templates
- Scenario context: Domain-specific descriptions for quant-stream
"""

from typing import Any
from dataclasses import asdict
import json
from jinja2 import Environment, StrictUndefined
from datetime import datetime

from ..types import WorkflowState, HypothesisFeedback
from ..recorder_utils import create_recorder_logger
from ..mlflow_utils import log_llm_interaction_to_mlflow
from .factor_propose import hypothesis_string

# ============================================================================
# SCENARIO CONTEXT
# ============================================================================

SCENARIO_DESCRIPTION = """Background of the scenario:
  The factor is a characteristic or variable used in quant investment that can help explain the returns and risks of a portfolio or a single asset. Factors are used by investors to identify and exploit sources of excess returns, and they are central to many quantitative investment strategies.
  Each number in the factor represents a numeric value for an instrument on a specific date.
  The user can optionally train a model to predict future returns based on factor values, or use the factors directly as trading signals.
  The factor is defined in the following parts:
  1. Name: The name of the factor.
  2. Description: The description of the factor.
  3. Formulation: The formulation of the factor.
  4. Expression: The executable expression of the factor.
  5. Variables: The variables or functions used in the formulation of the factor.
  The factor might not provide all the parts of the information above since some might not be applicable.
  Please specifically give all the hyperparameters in the factors like the window size, look back period, and so on. One factor should statically define one output with a static source data. For example, last 10 days momentum and last 20 days momentum should be two different factors.

The interface you should follow to write the runnable code:
  Your factor expression should follow the quant-stream interface to better interact with the user's system.
  Your expression must include at least one variable (e.g., `$open`, `$close`, `$high`, `$low`, `$volume`).
  Other parts contain arithmetic operators (`+, -, *, /`), logical operators (`&&, ||`), functions (`DELAY(), EXP(), LOG(), RANK(), etc.`), and conditional statements (`A?B:C`).
  The quant-stream system will automatically calculate factor values from these expressions using the Pathway streaming data processing framework.
  Factor values are computed in real-time or batch mode and stored in the system for backtesting and live trading.

The simulator user can use to test your factor:
  The factors will be processed by the quant-stream platform, a Pathway-based quantitative investment system.
  quant-stream is a real-time data processing and backtesting framework that supports both direct factor-based trading and ML-enhanced strategies.

  The system will automatically:
  1. Parse and validate factor expressions for syntax and semantic correctness.
  2. Calculate factor values from market data using the Pathway streaming engine.
  3. (Optional) Train ML models like LightGBM, XGBoost, or PyTorch models to predict returns based on factor values.
  4. Generate trading signals either directly from factors (when model_type=None) or from model predictions.
  5. Execute backtests using configurable strategies (TopkDropout, WeightedPortfolio, etc.).
  6. Evaluate portfolio performance with metrics including annualized return, Sharpe ratio, max drawdown, win rate, and more.

  The unified workflow supports seamless switching between direct factor trading and ML-based approaches.
"""

# ============================================================================
# PROMPTS
# ============================================================================

SYSTEM_PROMPT = """Please understand the following operation logic and then make your feedback that is suitable for the scenario:

{{ scenario }}

You will receive a hypothesis, multiple tasks with their factors, their results, and the SOTA result.
Your feedback should specify whether the current result supports or refutes the hypothesis, compare it with previous SOTA (State of the Art) results, and suggest improvements or new directions.
Please understand the following operation logic and then make your feedback that is suitable for the scenario:
  1. Logic Explanation:
      - Each hypothesis represents a theoretical framework that can be refined through multiple iterations
      - Focus on exploring various implementations within the same theoretical framework
      - Continuously optimize factor construction methods before considering direction changes

  2. Development Directions:
      - Hypothesis Refinement:
          - Suggest specific improvements in factor construction methodology
          - Propose alternative mathematical representations of the same theoretical concept
          - Identify potential variations in parameter selection and combination methods

      - Factor Enhancement:
          - Fine-tune existing factors through parameter or structure optimization
          - Explore different normalization and standardization approaches
          - Consider alternative window sizes and weighting schemes

      - Methodological Iteration:
          - Refine the mathematical expression while maintaining the core concept
          - Suggest complementary signals within the same theoretical framework
          - Propose robust variations of the current methodology

      - Regime-Agnostic Factor Diversity:
          - Ensure new hypothesis suggestions span different factor families
          - Avoid repeatedly suggesting variations of the same pattern (e.g., momentum / TS_STD)
          - Factor families to consider:
              * Momentum (continuation or reversal)
              * Mean reversion
              * Volatility structure (compression, expansion, clustering)
              * Liquidity / volume shocks
              * Price range & intraday microstructure
              * Event-driven / gap behavior
              * Cross-sectional regime patterns
          - Each new hypothesis should encourage at least one factor from a different conceptual class

      - Structural Novelty Requirement:
          - Do not suggest factors that only differ by window length changes
          - Each new factor must introduce a **new mechanism**, not a tuning of an old one

  3. Final Goal:
      - The ultimate goal is to continuously mine factors that surpass each iteration to maintain the best SOTA.
      - Factors should be robust across different market regimes (trend, range, high vol, low vol).

  When analyzing results:
  1. **Factor Construction Analysis:**
      - Evaluate how different construction methods affect factor performance
      - Identify which aspects of the construction process contribute most to performance
      - Suggest specific modifications to improve factor robustness

  2. **Parameter Sensitivity:**
      - Analyze the impact of different parameter choices
      - Recommend parameter ranges for further exploration
      - Identify critical components in the factor construction process

Focus on Continuous Refinement:
  - Exhaust all possible variations within the current theoretical framework
  - Document the effectiveness of different implementation approaches

Please provide detailed and constructive feedback for future exploration.
Respond in JSON format. Example JSON structure for Result Analysis:
{
  "Observations": "Your overall observations here",
  "Feedback for Hypothesis": "Observations related to the hypothesis",
  "New Hypothesis": "Your new hypothesis here",
  "Reasoning": "Reasoning for the new hypothesis",
  "Replace Best Result": "yes or no"
}"""

USER_PROMPT = """Target hypothesis:
{{ hypothesis_text }}
Tasks and Factors:
{% for task in task_details %}
  - {{ task.factor_name }}: {{ task.factor_description }}
    - Factor Formulation: {{ task.factor_formulation }}
    - Variables: {{ task.variables }}
    - Factor Implementation: {{ task.factor_implementation }}
    {% if task.factor_implementation == "False" %}
    **Note: This factor was not implemented in the current experiment. Only the hypothesis for implemented factors can be verified.**
    {% endif %}
{% endfor %}
Combined Results:
{{ combined_result }}

Analyze the combined result in the context of its ability to:
1. Support or refute the hypothesis.
2. Show improvement or deterioration compared to the SOTA experiment.

Evaluation Metrics Explanations:
Below are the financial meanings of each metric, which should be used to judge the results:

**Return Metrics:**
- annual_return: Annualized return of the strategy (higher is better)
- total_return: Cumulative return over the backtest period (higher is better)
- annual_volatility: Annualized volatility/risk (lower is better, but consider risk-adjusted returns)

**Risk-Adjusted Returns:**
- sharpe_ratio: Return per unit of risk, assuming 0 risk-free rate (higher is better, >1 is good, >2 is excellent)
- sortino_ratio: Return per unit of downside risk (higher is better)
- calmar_ratio: Return divided by max drawdown (higher is better)

**Risk Metrics:**
- max_drawdown: Maximum loss from peak to trough (smaller absolute value is better, e.g., -0.15 is better than -0.30)

**Win/Loss Statistics:**
- win_rate: Percentage of profitable periods (higher is better)
- avg_win: Average return in winning periods (higher is better)
- avg_loss: Average return in losing periods (closer to 0 is better, as losses are negative)
- profit_factor: Sum of wins / sum of losses (>1 is profitable, >2 is excellent)

**Information Coefficient (IC):**
- IC: Pearson correlation between predictions and actual returns (higher is better, >0.05 is good)
- Rank_IC: Spearman rank correlation between predictions and returns (higher is better, >0.05 is good)
- ICIR: IC Information Ratio (higher is better)
- Rank_ICIR: Rank IC Information Ratio (higher is better)

When judging the results:
  1. **Recommendation for Replacement:**
    - Consider holistic improvement across multiple metrics, not just a single metric
    - Key metrics to prioritize: sharpe_ratio, IC, annual_return, max_drawdown
    - If 2+ key metrics improve significantly, recommend replacement
    - If annual_return improves with stable or better sharpe_ratio, recommend replacement
    - Minor variations in less critical metrics are acceptable if key metrics improve

Note: Only factors with 'Factor Implementation' as True are implemented and tested in this experiment. If 'Factor Implementation' is False, the hypothesis for that factor cannot be verified in this run."""

# ============================================================================
# NODE FUNCTION
# ============================================================================

def feedback(state: WorkflowState, llm, node_number: str = "05") -> dict[str, Any]:
    """
    Generate feedback on hypothesis and experiment results.

    Inputs:
        - state['experiment']: Experiment object with backtest results from factor_backtest
        - state['hypothesis']: Hypothesis object from factor_propose
        - state['trace']: Trace object for SOTA comparison

    Outputs:
        - Returns dict with 'feedback': HypothesisFeedback object
        - Updates: trace.hist.append((hypothesis, experiment, feedback))
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    recorder = state.get("recorder")
    logger = create_recorder_logger(recorder)
    iteration = state.get("_mlflow_iteration", 0)
    llm_step = state.get("_mlflow_llm_step", 0)
    next_llm_step = llm_step + 1

    node_tag = f"{node_number}_feedback"
    with logger.tag(f"iter_{iteration}.{node_tag}"):
        logger.info("Starting feedback generation")

        trace = state.get("trace")
        hypothesis = state.get("hypothesis")
        experiment = state.get("experiment")

        # Get SOTA (state-of-the-art) for comparison
        sota_hypothesis, sota_experiment = trace.get_sota_hypothesis_and_experiment()
        is_first_iteration = (sota_experiment is None)

        # Prepare experiment results summary
        result = experiment.result if experiment else {}
        metrics = result.get("metrics", {}) if isinstance(result, dict) else {}

        # Build feedback context with ALL available metrics
        current_performance = f"""
Current Experiment Results:
Return Metrics:
- Annualized Return: {metrics.get('annual_return', 0):.2%}
- Total Return: {metrics.get('total_return', 0):.2%}
- Annual Volatility: {metrics.get('annual_volatility', 0):.2%}

Risk-Adjusted Returns:
- Sharpe Ratio: {metrics.get('sharpe_ratio', 0):.3f}
- Sortino Ratio: {metrics.get('sortino_ratio', 0):.3f}
- Calmar Ratio: {metrics.get('calmar_ratio', 0):.3f}

Risk Metrics:
- Max Drawdown: {metrics.get('max_drawdown', 0):.2%}

Win/Loss Statistics:
- Win Rate: {metrics.get('win_rate', 0):.2%}
- Average Win: {metrics.get('avg_win', 0):.4f}
- Average Loss: {metrics.get('avg_loss', 0):.4f}
- Profit Factor: {metrics.get('profit_factor', 0):.3f}

Information Coefficient (IC):
- IC (Pearson): {metrics.get('IC', 0):.4f}
- Rank IC (Spearman): {metrics.get('Rank_IC', 0):.4f}
- ICIR: {metrics.get('ICIR', 0):.4f}
- Rank ICIR: {metrics.get('Rank_ICIR', 0):.4f}

Number of Factors: {len(experiment.sub_tasks) if experiment else 0}
"""

        if is_first_iteration:
            sota_performance = "No previous SOTA available. This is the first iteration, so it should automatically become SOTA."
            sota_metrics = {}
        else:
            sota_metrics = sota_experiment.result.get("metrics", {}) if isinstance(sota_experiment.result, dict) else {}
            sota_performance = f"""
State-of-the-Art (SOTA) Performance:
Return Metrics:
- Annualized Return: {sota_metrics.get('annual_return', 0):.2%}
- Total Return: {sota_metrics.get('total_return', 0):.2%}
- Annual Volatility: {sota_metrics.get('annual_volatility', 0):.2%}

Risk-Adjusted Returns:
- Sharpe Ratio: {sota_metrics.get('sharpe_ratio', 0):.3f}
- Sortino Ratio: {sota_metrics.get('sortino_ratio', 0):.3f}
- Calmar Ratio: {sota_metrics.get('calmar_ratio', 0):.3f}

Risk Metrics:
- Max Drawdown: {sota_metrics.get('max_drawdown', 0):.2%}

Win/Loss Statistics:
- Win Rate: {sota_metrics.get('win_rate', 0):.2%}
- Average Win: {sota_metrics.get('avg_win', 0):.4f}
- Average Loss: {sota_metrics.get('avg_loss', 0):.4f}
- Profit Factor: {sota_metrics.get('profit_factor', 0):.3f}

Information Coefficient (IC):
- IC (Pearson): {sota_metrics.get('IC', 0):.4f}
- Rank IC (Spearman): {sota_metrics.get('Rank_IC', 0):.4f}
- ICIR: {sota_metrics.get('ICIR', 0):.4f}
- Rank ICIR: {sota_metrics.get('Rank_ICIR', 0):.4f}
"""

        # Build task_details for feedback prompt
        task_details = []
        for task in experiment.sub_tasks:
            task_details.append({
                "factor_name": task.name,
                "factor_description": task.description,
                "factor_formulation": task.formulation,
                "variables": task.variables,
                "factor_implementation": "True"  # Assume all factors are implemented
            })

        # Format combined result with metrics
        combined_result = f"""
{current_performance}

{sota_performance}
"""

        # Build messages for feedback generation
        messages = []
        messages.append(SystemMessage(
            Environment(undefined=StrictUndefined)
            .from_string(SYSTEM_PROMPT)
            .render(
                scenario=SCENARIO_DESCRIPTION,
            )
        ))
        messages.append(HumanMessage(
            Environment(undefined=StrictUndefined)
            .from_string(USER_PROMPT)
            .render(
                hypothesis_text=hypothesis_string(hypothesis),
                current_performance=current_performance,
                sota_performance=sota_performance,
                task_details=task_details,
                combined_result=combined_result
            )
        ))

        # Get LLM response
        try:
            logger.info("Calling LLM for feedback generation...")

            response = llm.invoke(messages)
            response_content = response.content if hasattr(response, 'content') else response
            raw_response_content = response_content
            
            # Log full request and response together
            llm_log = "=" * 80 + "\nREQUEST\n" + "=" * 80 + "\n\n"
            llm_log += "\n\n".join([f"=== {msg.__class__.__name__} ===\n{msg.content}" for msg in messages])
            llm_log += "\n\n" + "=" * 80 + "\nRESPONSE\n" + "=" * 80 + "\n\n"
            llm_log += response_content
            logger.log_text(
                "llm_interaction",
                llm_log,
                artifact_path=f"alphacopilot/iter_{iteration}/llm/{node_tag}",
            )

            log_llm_interaction_to_mlflow(
                recorder,
                node_tag,
                messages,
                raw_response_content,
                step=iteration,
            )
            
            logger.info(f"LLM response preview (first 200 chars): {response_content[:200]}...")

            # Extract JSON from response (handle various formats)
            response_content = response_content.strip()

            # Try to extract JSON from markdown code fences
            if '```json' in response_content or '```' in response_content:
                # Find content between ``` markers
                import re
                json_match = re.search(r'```(?:json)?\s*\n(.*?)\n```', response_content, re.DOTALL)
                if json_match:
                    response_content = json_match.group(1).strip()
                else:
                    # Try removing just the first and last ``` lines
                    lines = response_content.split('\n')
                    if lines[0].strip().startswith('```'):
                        lines = lines[1:]
                    if lines and lines[-1].strip() == '```':
                        lines = lines[:-1]
                    response_content = '\n'.join(lines)

            # Try to extract JSON object from text (handle LLM adding commentary)
            if not response_content.strip().startswith('{'):
                import re
                # Look for JSON object in the response
                json_match = re.search(r'\{.*\}', response_content, re.DOTALL)
                if json_match:
                    response_content = json_match.group(0)
                    logger.info("Extracted JSON object from LLM commentary")

            # Parse JSON with error handling
            response_dict = None
            try:
                response_dict = json.loads(response_content)
            except json.JSONDecodeError as e:
                logger.warning(f"JSON parse error in feedback: {e}. Attempting to fix escape sequences...")
                # Replace all single backslashes with double backslashes
                fixed_content = response_content.replace('\\', '\\\\')
                try:
                    response_dict = json.loads(fixed_content)
                    logger.info("✓ Successfully parsed feedback JSON after fixing escape sequences")
                except json.JSONDecodeError as e2:
                    logger.error(f"Failed to parse feedback JSON: {e2}")
                    logger.error(f"Content: {response_content[:500]}...")
                    # Will raise exception and use fallback below
                    raise

            # Parse response using correct key names
            observations = response_dict.get("Observations", "")
            hypothesis_evaluation = response_dict.get("Feedback for Hypothesis", "")
            new_hypothesis = response_dict.get("New Hypothesis", "")
            reason = response_dict.get("Reasoning", "")

            # Parse decision (yes/no)
            replace_best = response_dict.get("Replace Best Result", "no")
            decision = replace_best.lower() == "yes"

            feedback_obj = HypothesisFeedback(
                observations=observations,
                hypothesis_evaluation=hypothesis_evaluation,
                new_hypothesis=new_hypothesis,
                reason=reason,
                decision=decision,
            )
        except Exception as e:
            logger.error(f"✗ Feedback generation failed: {str(e)}")
            # Create default feedback
            # First iteration always becomes SOTA, subsequent iterations use comprehensive comparison
            if is_first_iteration:
                is_better = True
                reason = "First iteration"
            else:
                # Compare multiple metrics for more robust decision
                sharpe_better = metrics.get('sharpe_ratio', 0) > sota_metrics.get('sharpe_ratio', 0)
                ic_better = metrics.get('IC', 0) > sota_metrics.get('IC', 0)
                return_better = metrics.get('annual_return', 0) > sota_metrics.get('annual_return', 0)

                # Better if at least 2 out of 3 key metrics improve
                improvements = sum([sharpe_better, ic_better, return_better])
                is_better = improvements >= 2

                reason = f"Sharpe: {metrics.get('sharpe_ratio', 0):.3f}, IC: {metrics.get('IC', 0):.4f}, Return: {metrics.get('annual_return', 0):.2%}"

            feedback_obj = HypothesisFeedback(
                observations=current_performance,
                hypothesis_evaluation="Automated evaluation (LLM feedback failed)",
                new_hypothesis="Continue exploring similar patterns with emphasis on IC and Sharpe improvements",
                reason=reason,
                decision=is_better,
            )
        
        logger.log_json(
            "feedback",
            asdict(feedback_obj),
            artifact_path=f"alphacopilot/iter_{iteration}/state/{node_tag}",
        )
        if recorder and recorder.active_run:
            try:
                recorder.log_metrics(
                    step=iteration,
                    feedback_replace_best=float(feedback_obj.decision),
                )
                recorder.log_metrics(
                    feedback_replace_best=float(feedback_obj.decision),
                )
            except Exception:
                pass

        # Update trace history
        trace.hist.append((hypothesis, experiment, feedback_obj))

        logger.info(f"\n{'='*60}")
        logger.info(f"Feedback Decision: {'✓ New SOTA' if feedback_obj.decision else '✗ Not better than SOTA'}")
        logger.info(f"{'='*60}\n")

        # Prepare for next iteration - use new_hypothesis as potential_direction
        new_direction = feedback_obj.new_hypothesis if feedback_obj.new_hypothesis else None

        log_msg = f"{node_tag}: feedback generated (replace_sota={feedback_obj.decision}) at {datetime.now().isoformat()}"
        next_iteration = iteration + 1

        logger.flush()

        return {
            "feedback": feedback_obj,
            "trace": trace,  # Return updated trace
            "potential_direction": new_direction,  # Guide next iteration
            "agent_logs": [log_msg],
            "_mlflow_iteration": next_iteration,
            "_mlflow_llm_step": next_llm_step,
        }
