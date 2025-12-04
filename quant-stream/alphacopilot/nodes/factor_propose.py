"""
Factor Propose Node - Generate market hypothesis to guide factor creation.

This module contains:
- Node function: factor_propose()
- Prompts: System, user, and output format templates
- Scenario context: Domain-specific descriptions for quant-stream
- Helper functions: hypothesis_string()
"""

from typing import Any
import json
from jinja2 import Environment, StrictUndefined
from datetime import datetime

from ..types import WorkflowState, Hypothesis
from ..recorder_utils import create_recorder_logger
from ..mlflow_utils import log_llm_interaction_to_mlflow

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

Trading Strategy Context (IMPORTANT):
  **This is a SHORT-TERM trading strategy.** The factors you generate will be used to:
  1. Compute factor values for a universe of stocks daily.
  2. Train an ML model (e.g., LightGBM, LSTM) to predict next-day returns based on these factor values.
  3. Rank stocks by predicted returns and select the TOP-K stocks to BUY each day.
  4. SELL these positions the NEXT trading day (1-day holding period).
  
  **Key implications for factor design:**
  - Factors should capture SHORT-TERM price movements and momentum (prefer lookback windows under 30 days).
  - Focus on signals that predict NEXT-DAY returns, not long-term trends.
  - Factors like 5-day, 10-day, or 20-day windows are ideal; avoid very long windows (60+ days) unless capturing mean-reversion.
  - Consider daily OHLCV patterns, short-term momentum, volume spikes, and recent price action.

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
  3. Train ML models like LightGBM, XGBoost, or PyTorch models to predict next-day returns based on factor values.
  4. Rank stocks by model predictions and select top-K stocks to buy daily.
  5. Execute backtests using TopkDropout strategy (buy top stocks, sell next day).
  6. Evaluate portfolio performance with metrics including annualized return, Sharpe ratio, max drawdown, win rate, and more.

  The unified workflow supports seamless switching between direct factor trading and ML-based approaches.

Regime-Agnostic Factor Diversity (Critical):
  Backtests may occur under any market regime (trend, range, high vol, low vol).
  Therefore, generated factors must be **regime-agnostic** and cover **multiple signal families**, not just momentum.

  Rules:
  1. **At least one factor per batch must come from a different factor family**, such as:
     - Momentum (continuation or reversal)
     - Mean reversion
     - Volatility structure (compression, expansion, clustering)
     - Liquidity / volume shocks
     - Price range & intraday microstructure
     - Event-driven / gap behavior
     - Cross-sectional regime patterns (beta shocks, dispersion changes)

  2. Do **not** repeatedly generate variations of:
     - minor window tweaks or ranked versions of the same expression

  3. Each factor must represent a **distinct economic intuition**, not a mathematical rewrite.

  4. Never assume a specific market regime; factors must remain valid whether markets are trending, mean-reverting, choppy, or volatile.

  5. **Do not over-focus on any single style**, such as:
     - pure momentum
     - pure mean-reversion
     - volatility-normalized momentum
     - volume-only factors
     - candle-only factors
"""

# ============================================================================
# PROMPTS
# ============================================================================

SYSTEM_PROMPT = """The user is working on generating new hypotheses for the {{targets}} in a data-driven research and development process.
The {{targets}} are used in the following scenario:
{{scenario}}
The user has already proposed several hypotheses and conducted evaluations on them. This information will be provided to you.
Your task is to check whether a hypothesis has already been generated. If one exists, follow it or generate an improved version.
{% if hypothesis_specification %}
To assist you in formulating new hypotheses, the user has provided some additional information:
{{hypothesis_specification}}.
**Important:** If the hypothesis_specification outlines the next steps you need to follow, ensure you adhere to those instructions.
{% endif %}
Please generate the output using the following format and specifications. Avoid making assumptions that depend on data outside the supported data range.
{{ hypothesis_output_format }}"""

USER_PROMPT = """{% if hypothesis_and_feedback|length == 0 %}It is the first round of hypothesis generation. The user has no hypothesis on this scenario yet. You are encouraged to propose an innovative hypothesis that diverges significantly from existing perspectives.
{% else %}It is not the first round, the user has made several hypothesis on this scenario and did several evaluation on them.
The former hypothesis and the corresponding feedbacks are as follows (focus on the last one & the new hypothesis that it provides and reasoning to see if you agree):
{{ hypothesis_and_feedback }}
{% endif %}
{% if RAG %}
To assist you in generating new {{targets}}, we have provided the following information: {{RAG}}.
**Note:** The provided RAG is for reference only.
You must carefully assess whether the RAG aligns with the {{targets}}.
If it does not, it should not be used. Exercise caution and make your own judgment.
{% endif %}
Also generate the relevant keys for the reasoning and the distilled knowledge that follows. For those keys, in particular for knowledge, explain in the context of the specific scenario to build up domain knowledge in the specific field rather than general knowledge."""

OUTPUT_FORMAT = """**CRITICAL: OUTPUT ONLY VALID JSON - NO EXPLANATIONS OR COMMENTARY**

Your response must be ONLY the JSON object below with NO additional text before or after.
Do NOT include explanations, reasoning, or commentary.
Do NOT start with "Here is the JSON..." or similar preamble.
Output ONLY valid JSON that starts with { and ends with }.

The schema is as follows:
{
  "hypothesis": "A SINGLE LINE OF TEXT. The new hypothesis generated based on the information provided.",
  "concise_knowledge": "A SINGLE LINE OF TEXT. Transferable knowledge based on theoretical principles. Use conditional grammar. eg. 'If...., ..; When..., .; and etc' Make sure that you state things clearly without ambiguity. Eg. avoid saying 'previous hypothesis', because one wouldn't know what that is.",
  "concise_observation": "A SINGLE LINE OF TEXT. It focuses on the observation of the given scenario, data characteristics, or previous experiences (failures & succeses).",
  "concise_justification": "A SINGLE LINE OF TEXT. Justify the hypothesis based on theoretical principles or initial assumptions.",
  "concise_specification": "A SINGLE LINE OF TEXT. Define the scope, conditions, constraints of the hypothesis. Specify the expected relationships, variables, and thresholds, ensuring testability and relevance to the observed data."
}"""

POTENTIAL_DIRECTION_TEMPLATE = """It's the first round, the user provided a potential direction: "{{ potential_direction }}". Referring to it, you need to transform it into a hypothesis in formal language that is clear and actionable for factor generation. Consider the following aspects while formulating the hypothesis:
1. **Clarity**: Ensure the hypothesis is specific and unambiguous.
2. **Actionability**: The hypothesis should suggest a clear path for experimentation or investigation.
3. **Relevance**: Ensure the hypothesis is directly related to the potential direction provided by the user."""

HYPOTHESIS_AND_FEEDBACK_TEMPLATE = """{% for hypothesis, experiment, feedback in trace.hist[-10:] %}
Hypothesis {{ loop.index }}: {{ hypothesis.hypothesis }}

Factors Generated:
{% for task in experiment.sub_tasks %}  - {{ task.name }}: {{ task.expression }}
{% endfor %}
Observation on the result with the hypothesis: {{ feedback.observations }}
Feedback on the original hypothesis: {{ feedback.hypothesis_evaluation }}
New Feedback for Context (For you to agree or improve upon): {{ feedback.new_hypothesis }}
Reasoning for new hypothesis: {{ feedback.reason }}
Did changing to this hypothesis work? (focus on the change): {{ feedback.decision }}

{% endfor %}"""

HYPOTHESIS_SPECIFICATION = """1. **Data-Driven Hypothesis Formation:**
  - Ground hypotheses within the scope of available data for seamless testing.
  - Align hypotheses with the temporal, cross-sectional, and distributional properties of the data.
  - Avoid overfitting by focusing on robust, economically intuitive, and innovative relationships.

2. **Justification of the Hypothesis:**
  - Use observed market patterns to creatively infer underlying economic or behavioral drivers.
  - Build on empirical evidence while exploring innovative connections or untested relationships.
  - Propose actionable insights that challenge conventional assumptions, yet remain testable.
  - Emphasize the factor's potential to uncover unique, predictive market behaviors.

3. **Continuous Optimization and Exploration:**
    - Refine the first hypothesis iteratively by testing across different variants.
    - Incorporate feedback from empirical results to enhance the factor's predictive power.

4. **Factor Family Coverage Rule:**
  - When generating 2-3 factors, each must belong to a different factor family, unless the hypothesis explicitly restricts otherwise.
  - Factor families include:
    * Price Momentum
    * Mean Reversion
    * Volatility / Range
    * Volume & Liquidity
    * Microstructure
    * Cross-sectional patterns
    * Seasonality / Temporal patterns

5. **Structural Novelty Constraint:**
  - Factors must not be structural variations of previously tried failing patterns.
  - Avoid generating factors that only differ by:
    * window length changes
    * replacing TS_STD with TS_MAD or TS_VAR
    * ranking the same numerator/denominator
  - Each new factor must introduce a **new mechanism**, not a tuning of an old one.

6. **All-Regime Compatibility (Not regime-specific):**
  - Factors should be designed so that they:
    * are interpretable in both trending and non-trending markets
    * work under both high and low volatility
    * capture signals observable under changing liquidity regimes
  - Do not assume any single regime; generate factors that could theoretically perform under any regime, and let the backtester discover which ones win.

7. **Exploration vs Exploitation:**
  - If the hypothesis is new → explore new styles
  - If the hypothesis is an iteration → refine within the same conceptual block
  - But never generate **multiple similar factors in one batch** unless explicitly instructed"""

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def hypothesis_string(hypothesis: Hypothesis) -> str:
    """Format hypothesis as string for use in prompts."""
    return f"""Hypothesis: {hypothesis.hypothesis}
Reason: {hypothesis.reason}
Concise Reason: {hypothesis.concise_reason}
Concise Observation: {hypothesis.concise_observation}
Concise Justification: {hypothesis.concise_justification}
Concise Knowledge: {hypothesis.concise_knowledge}
"""

# ============================================================================
# NODE FUNCTION
# ============================================================================

def factor_propose(state: WorkflowState, llm, node_number: str = "01") -> dict[str, Any]:
    """
    Generate market hypothesis to guide factor creation.
    
    Inputs:
        - state['trace']: Trace object with history
        - state['potential_direction']: Optional initial direction (first iteration)
    
    Outputs:
        - Returns dict with 'hypothesis': Hypothesis object
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    recorder = state.get("recorder")
    logger = create_recorder_logger(recorder)
    iteration = state.get("_mlflow_iteration", 0)

    node_tag = f"{node_number}_factor_propose"
    with logger.tag(f"iter_{iteration}.{node_tag}"):
        trace = state.get("trace")
        current_iteration = len(trace.hist) + 1
        logger.info("=" * 60)
        logger.info(f"ITERATION {current_iteration}")
        logger.info("=" * 60)
        logger.info("Starting hypothesis generation")

        potential_direction = state.get("potential_direction")

        # Build hypothesis_and_feedback based on trace history
        if len(trace.hist) > 0:
            hypothesis_and_feedback = (
                Environment(undefined=StrictUndefined)
                .from_string(HYPOTHESIS_AND_FEEDBACK_TEMPLATE)
                .render(trace=trace)
            )
        elif potential_direction is not None:
            hypothesis_and_feedback = (
                Environment(undefined=StrictUndefined)
                .from_string(POTENTIAL_DIRECTION_TEMPLATE)
                .render(potential_direction=potential_direction)
            )
        else:
            hypothesis_and_feedback = "No previous hypothesis and feedback available since it's the first round. You are encouraged to propose an innovative hypothesis that diverges significantly from existing perspectives."

        # Build messages
        messages = []
        messages.append(SystemMessage(
            Environment(undefined=StrictUndefined)
            .from_string(SYSTEM_PROMPT)
            .render(
                targets="factors",
                scenario=SCENARIO_DESCRIPTION,
                hypothesis_output_format=OUTPUT_FORMAT,
                hypothesis_specification=HYPOTHESIS_SPECIFICATION,
            )
        ))
        messages.append(HumanMessage(
            Environment(undefined=StrictUndefined)
            .from_string(USER_PROMPT)
            .render(
                targets="factors",
                hypothesis_and_feedback=hypothesis_and_feedback,
                RAG=None  # No RAG for now
            )
        ))

        # Get LLM response
        logger.info("Calling LLM for hypothesis generation...")

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

        llm_step = state.get("_mlflow_llm_step", 0)
        next_llm_step = llm_step + 1
        log_llm_interaction_to_mlflow(
            recorder,
            node_tag,
            messages,
            raw_response_content,
            step=iteration,
        )
        
        logger.info(f"LLM response preview (first 200 chars): {response_content[:200]}...")

        # Strip markdown code fences if present
        response_content = response_content.strip()
        if response_content.startswith('```'):
            # Remove opening fence (```json or ```)
            lines = response_content.split('\n')
            lines = lines[1:]  # Skip first line with ```
            # Remove closing fence
            if lines and lines[-1].strip() == '```':
                lines = lines[:-1]
            response_content = '\n'.join(lines)

        # Parse JSON with LaTeX escape sequence handling
        try:
            response_dict = json.loads(response_content)
        except json.JSONDecodeError as e:
            logger.warning(f"JSON parse error: {e}. Attempting to fix escape sequences...")
            # Replace all single backslashes with double backslashes (except already escaped ones)
            # This handles LaTeX in JSON strings: \text → \\text, \frac → \\frac
            fixed_content = response_content.replace('\\', '\\\\')
            try:
                response_dict = json.loads(fixed_content)
                logger.info("✓ Successfully parsed JSON after fixing escape sequences")
            except json.JSONDecodeError as e2:
                logger.error(f"Failed to parse JSON even after fixes: {e2}")
                logger.error(f"Response content (first 500 chars): {response_content[:500]}...")
                raise

        # Log parsed response structure
        logger.info(f"Response keys: {list(response_dict.keys())}")

        # Create Hypothesis object
        concise_spec = response_dict.get("concise_specification", "")
        hypothesis = Hypothesis(
            hypothesis=response_dict.get("hypothesis", ""),
            reason=concise_spec,  # Use specification as detailed reason
            concise_reason=concise_spec,  # Use specification as concise reason
            concise_observation=response_dict.get("concise_observation", ""),
            concise_justification=response_dict.get("concise_justification", ""),
            concise_knowledge=response_dict.get("concise_knowledge", ""),
        )

        logger.info(f"Generated hypothesis: {hypothesis.hypothesis}")
        logger.log_json(
            "hypothesis",
            {
                "iteration": iteration,
                "hypothesis": hypothesis.hypothesis,
                "concise_observation": hypothesis.concise_observation,
                "concise_justification": hypothesis.concise_justification,
                "concise_knowledge": hypothesis.concise_knowledge,
            },
            artifact_path=f"alphacopilot/iter_{iteration}/state/{node_tag}",
        )
        
    logger.flush()

    # Append short agent log for this run (annotated reducer will append)
    log_msg = f"{node_number}_factor_propose: generated hypothesis at {datetime.now().isoformat()}"
    return {
        "hypothesis": hypothesis,
        "agent_logs": [log_msg],
        "_mlflow_llm_step": next_llm_step,
    }
