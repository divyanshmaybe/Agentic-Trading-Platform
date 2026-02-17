"""
Factor Construct Node - Construct factors based on hypothesis.

This module contains:
- Node function: factor_construct()
- Prompts: System, user, and output format templates
- Function library: Complete description of available factor operations
- Scenario context: Domain-specific descriptions for quant-stream
"""

from typing import Any
import json
from jinja2 import Environment, StrictUndefined
from datetime import datetime

from ..types import WorkflowState, Experiment, FactorTask
from ..recorder_utils import create_recorder_logger
from ..mlflow_utils import (
    log_llm_interaction_to_mlflow,
    log_generated_factors_to_mlflow,
)
from .factor_propose import hypothesis_string, HYPOTHESIS_AND_FEEDBACK_TEMPLATE

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
  Other parts contain arithmetic operators (`+, -, *, /`), comparison operators (`>, <, >=, <=, ==, !=`), logical operators (`&&, ||, &, |`), and functions (`DELAY(), EXP(), LOG(), RANK(), etc.`).
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
# FUNCTION LIBRARY
# ============================================================================

FUNCTION_LIBRARY = """Only the following operations are allowed in expressions:
### **Cross-sectional Functions**
- **RANK(A)**: Ranking of each element in the cross-sectional dimension of A.
- **ZSCORE(A)**: Z-score of each element in the cross-sectional dimension of A.
- **MEAN(A)**: Mean value of each element in the cross-sectional dimension of A.
- **STD(A)**: Standard deviation in the cross-sectional dimension of A.
- **SKEW(A)**: Skewness in the cross-sectional dimension of A.
- **MAX(A)**: Maximum value in the cross-sectional dimension of A.
- **MIN(A)**: Minimum value in the cross-sectional dimension of A.
- **MEDIAN(A)**: Median value of each element in the cross-sectional dimension of A

### **Time-Series Functions** (⚠️ ALL period/window parameters (n, p) MUST be positive integers > 0)
- **DELTA(A, n)**: Change in value of A over n periods (n > 0).
- **DELAY(A, n)**: Value of A delayed by n periods (n > 0).
- **TS_MEAN(A, n)**: Mean value of sequence A over the past n days (n > 0).
- **TS_SUM(A, n)**: Sum of sequence A over the past n days (n > 0).
- **TS_RANK(A, n)**: Time-series rank of the last value of A in the past n days (n > 0).
- **TS_ZSCORE(A, n)**: Z-score for each sequence in A over the past n days (n > 0).
- **TS_MEDIAN(A, n)**: Median value of sequence A over the past n days (n > 0).
- **TS_PCTCHANGE(A, p)**: Percentage change in the value of sequence A over p periods (p > 0).
- **TS_MIN(A, n)**: Minimum value of A in the past n days (n > 0).
- **TS_MAX(A, n)**: Maximum value of A in the past n days (n > 0).
- **TS_ARGMAX(A, n)**: The index (relative to the current time) of the maximum value of A over the past n days (n > 0).
- **TS_ARGMIN(A, n)**: The index (relative to the current time) of the minimum value of A over the past n days (n > 0).
- **TS_QUANTILE(A, p, q)**: Rolling quantile of sequence A over the past p periods (p > 0), where q is the quantile value between 0 and 1.
- **TS_STD(A, n)**: Standard deviation of sequence A over the past n days (n > 0).
- **TS_VAR(A, p)**: Rolling variance of sequence A over the past p periods (p > 0).
- **TS_CORR(A, B, n)**: Correlation coefficient between sequences A and B over the past n days (n > 0).
- **TS_COVARIANCE(A, B, n)**: Covariance between sequences A and B over the past n days (n > 0).
- **TS_MAD(A, n)**: Rolling Median Absolute Deviation of sequence A over the past n days (n > 0).
- **PERCENTILE(A, q, p)**: Quantile of sequence A, where q is the quantile value between 0 and 1. If p is provided, it calculates the rolling quantile over the past p periods (p > 0).
- **HIGHDAY(A, n)**: Number of days since the highest value of A in the past n days (n > 0).
- **LOWDAY(A, n)**: Number of days since the lowest value of A in the past n days (n > 0).
- **SUMAC(A, n)**: Cumulative sum of A over the past n days (n > 0).

### **Moving Averages and Smoothing Functions** (⚠️ ALL period/window parameters MUST be positive integers > 0)
- **SMA(A, n, m)**: Simple moving average of A over n periods (n > 0) with modifier m.
- **WMA(A, n)**: Weighted moving average of A over n periods (n > 0), with weights decreasing from 0.9 to 0.9^(n).
- **EMA(A, n)**: Exponential moving average of A over n periods (n > 0), where the decay factor is 2/(n+1).
- **DECAYLINEAR(A, d)**: Linearly weighted moving average of A over d periods (d > 0), with weights increasing from 1 to d.

### **Mathematical Operations**
- **PROD(A, n)**: Product of values in A over the past n days (n > 0). Use `*` for general multiplication.
- **LOG(A)**: Natural logarithm of each element in A.
- **SQRT(A)**: Square root of each element in A.
- **POW(A, n)**: Raise each element in A to the power of n.
- **SIGN(A)**: Sign of each element in A, one of 1, 0, or -1.
- **EXP(A)**: Exponential of each element in A.
- **ABS(A)**: Absolute value of A.
- **MAX(A, B)**: Maximum value between A and B.
- **MIN(A, B)**: Minimum value between A and B.
- **INV(A)**: Reciprocal (1/x) of each element in sequence A.
- **FLOOR(A)**: Floor of each element in sequence A.

### **Conditional and Logical Functions**
- **COUNT(C, n)**: Count of samples satisfying condition C in the past n periods (n > 0). Here, C is a logical expression, e.g., `$close > $open`.
- **SUMIF(A, n, C)**: Sum of A over the past n periods (n > 0) if condition C is met. Here, C is a logical expression.
- **FILTER(A, C)**: Filtering multi-column sequence A based on condition C. Here, C is presented in a logical expression form, with the same size as A.
- **TERNARY(C, A, B)**: Conditional expression that returns A when condition C is truthy, or B otherwise. Generated from `C ? A : B`.
- **(C1)&&(C2)**: Logical operation "and". Both C1 and C2 are logical expressions, such as A > B.
- **(C1)||(C2)**: Logical operation "or". Both C1 and C2 are logical expressions, such as A > B.

### **Regression and Residual Functions**
- **REGBETA(A, B, n)**: Regression coefficient (slope) of A on B using the past n samples (n > 0). Computes linear regression to find the beta coefficient.
- **REGRESI(A, B, n)**: Residual of regression of A on B using the past n samples (n > 0). Returns the difference between actual and predicted values.

### **Technical Indicators** (⚠️ ALL period/window parameters MUST be positive integers > 0)
- **RSI(A, n)**: Relative Strength Index of sequence A over n periods (n > 0). Measures momentum by comparing the magnitude of recent gains to recent losses.
- **MACD(A, short_window, long_window)**: Moving Average Convergence Divergence (MACD) of sequence A (short_window > 0, long_window > 0), calculated as the difference between the short-term (short_window) and long-term (long_window) exponential moving averages.
- **BB_MIDDLE(A, n)**: Middle Bollinger Band, calculated as the n-period (n > 0) simple moving average of sequence A.
- **BB_UPPER(A, n)**: Upper Bollinger Band, calculated as middle band plus two standard deviations of sequence A over n periods (n > 0).
- **BB_LOWER(A, n)**: Lower Bollinger Band, calculated as middle band minus two standard deviations of sequence A over n periods (n > 0).


Note that:
- Only the variables provided in data (e.g., `$open`), arithmetic operators (`+, -, *, /`), comparison operators (`>, <, >=, <=, ==, !=`), logical operators (`&&, ||, &, |`), and the operations above are allowed in the factor expression.
- Make sure your factor expression contain at least one variables within the dataframe columns (e.g. $open), combined with registered operations above. Do NOT use any undeclared variable (e.g. 'n', 'w_1') and undefined symbols (e.g., '=') in the expression.
- Pay attention to the distinction between operations with the TS prefix (e.g., `TS_STD()`) and those without (e.g., `STD()`).
- **CRITICAL: ALL period/window parameters (n, p, d) in time-series functions MUST be positive integers (> 0). NEVER use negative values as this causes data leakage by looking forward in time.**"""

# ============================================================================
# PROMPTS
# ============================================================================

SYSTEM_PROMPT = """The user is trying to generate new {{targets}} based on the hypothesis generated in the previous step.
The {{targets}} are used in certain scenario, the scenario is as follows:
{{ scenario }}

The user will use the {{targets}} generated to do some experiments. The user will provide this information to you:
1. The target hypothesis you are targeting to generate {{targets}} for.
2. The hypothesis generated in the previous steps and their corresponding feedbacks.
3. Former proposed {{targets}} on similar hypothesis.
4. Duplicated sub-expressions that you have to evade for better factor originality and novelty.
5. Some additional information to help you generate new {{targets}}.

**Important Note on Custom Factors:**
The user may have already provided some custom factor expressions that will be included in the workflow alongside your generated factors. Your goal is to generate factors that complement these existing factors by exploring different market signals, relationships, or perspectives. Aim for diversity and avoid duplicating the patterns in any pre-existing custom factors.


1. **2-3 Factors per Generation:**
  - Ensure each generation produces 2-3 factors.
  - Balance simplicity and innovation to build a robust factor library.
  - Note that each factor is independent. Please do NOT reference other factors within the factor expression.

2. **Expression Format Requirements:**
  - **CRITICAL**: Each factor must be a SINGLE expression without variable assignments
  - **DO NOT use** variable definitions like `VAR_X = ...; VAR_Y = ...; expression`
  - **DO NOT use** semicolons (`;`) to chain operations
  - **DO NOT use** assignment operators (`=`)
  - Write all computations inline using nested function calls
  - Example of INCORRECT format: `VAR_R5 = TS_PCTCHANGE($close, 5); VAR_R60 = TS_PCTCHANGE($close, 60); VAR_R5 / VAR_R60`
  - Example of CORRECT format: `TS_PCTCHANGE($close, 5) / TS_PCTCHANGE($close, 60)`
  - If you need to reuse a sub-expression, just repeat it inline (the system will cache it automatically)

3.**Key Considerations in Factor Construction:**
  - **Data Preprocessing and Standardization:**
      - Avoid using raw prices and volumes directly due to scale differences
      - Use relative changes or standardized data (e.g., RANK(), ZSCORE())
      - Convert prices to returns, e.g. `(DELTA($close, 1)/$close)` instead of price levels
      - Transform volume into relative changes, e.g. `(DELTA($volume, 1)/$volume)

  - **Time Series Processing:**
      - **CRITICAL: ALL period/window parameters MUST be positive integers (> 0). NEVER use negative or zero values.**
      - Consider appropriate sample periods for indicators requiring historical data
      - Choose suitable window sizes for moving averages SMA(), EMA(), WMA()

  - **Normalization and Stability:**
      - Add small constants (e.g., 1e-8) to denominators to prevent division by zero
      - Use TS_ZSCORE() for factor value standardization
      - Consider SIGN() to reduce impact of extreme values
      - Apply MAX(MIN(x, upper), lower) for value truncation

  - **Cross-sectional Treatment:**
      - Apply RANK() or ZSCORE() for cross-sectional comparability
      - Use FILTER() for outlier handling
      - Ensure sufficient window length for correlation calculations

  - **Robustness Considerations:**
      - Validate factor stability across multiple time windows
      - Consider TS_MEDIAN() over TS_MEAN() to reduce outlier impact
      - Apply moving averages to smooth high-frequency variations

  - **Flexibility Considerations:**
      - Allow for a range of values or flexibility when defining factors, rather than imposing strict equality constraints.
      - For example, in expression `(TS_MIN($low, 10) == DELAY(TS_MIN($low, 10), 1))`, `==` is too restrictive.
      - Instead, use a range-based approach like: `(TS_MIN($low, 10) < DELAY(TS_MIN($low, 10), 1) + 1/10 * TS_STD($low, 20)) && (TS_MIN($low, 10) > DELAY(TS_MIN($low, 10), 1) - 1/10 * TS_STD($low, 20))`.

  - **Handling Duplicated Sub-expressions:**
        - When given specific duplicated sub-expressions to avoid, ensure new factor expressions use alternative calculations
        - Replace duplicated patterns with semantically similar but structurally different expressions
        - For example, if `ABS($close - $open)` is flagged as duplicated:
            - Consider using `($high - $low)` for price range
            - Use `SIGN($close - $open) * ($close - $open)` for directional magnitude
            - Explore other price difference combinations like `($high - $low) / ($open + $close)`
        - Maintain factor interpretability while avoiding structural repetition
        - Focus on unique combinations of operators and variables to ensure originality

  - **Factor Family Coverage Rule:**
        - When generating 2-3 factors, each must belong to a different factor family, unless the hypothesis explicitly restricts otherwise.
        - Factor families include:
            * Price Momentum
            * Mean Reversion
            * Volatility / Range
            * Volume & Liquidity
            * Microstructure
            * Cross-sectional patterns
            * Seasonality / Temporal patterns

  - **Structural Novelty Constraint:**
        - Factors must not be structural variations of previously tried failing patterns.
        - Avoid generating factors that only differ by:
            * window length changes
            * replacing TS_STD with TS_MAD or TS_VAR
            * ranking the same numerator/denominator
        - Each new factor must introduce a **new mechanism**, not a tuning of an old one.

  - **All-Regime Compatibility (Not regime-specific):**
        - Factors should be designed so that they:
            * are interpretable in both trending and non-trending markets
            * work under both high and low volatility
            * capture signals observable under changing liquidity regimes
        - Do not assume any single regime; generate factors that could theoretically perform under any regime, and let the backtester discover which ones win.

  - **Exploration vs Exploitation:**
        - If the hypothesis is new → explore new styles
        - If the hypothesis is an iteration → refine within the same conceptual block
        - But never generate **multiple similar factors in one batch** unless explicitly instructed

Please generate the output following the format below:
{{ experiment_output_format }}

**CRITICAL SYNTAX REQUIREMENTS:**
- Each expression must be a SINGLE line without variable assignments
- NO semicolons (;), NO assignment operators (=)
- Use nested function calls and inline all computations
- Do not use undeclared variables or custom variable names
- Only use $close, $open, $high, $low, $volume and the allowed functions
- Allowed operators: arithmetic (`+, -, *, /`), comparison (`>, <, >=, <=, ==, !=`), logical (`&&, ||, &, |`)

**CRITICAL OUTPUT REQUIREMENTS:**
- Your response must be ONLY valid JSON with NO additional text
- Do NOT add explanations, commentary, or reasoning
- Do NOT start with "Here is..." or "I will generate..." or any preamble
- Output must start with { and end with } - nothing else"""

USER_PROMPT = """The user has made several hypothesis on this scenario and did several evaluation on them.
The target hypothesis you are targeting to generate {{targets}} for is as follows:
{{ target_hypothesis }}

The former hypothesis and the corresponding feedbacks are as follows:
{{ hypothesis_and_feedback }}

When constructing factor expressions, you are restricted to utilizing only the following daily-level variables:
- $open: open price of the stock on that day.
- $close: close price of the stock on that day.
- $high: high price of the stock on that day.
- $low: low price of the stock on that day.
- $volume: volume of the stock on that day.

Allowed operators and functions in factor expressions are:
{{function_lib_description}}

{% if validation_error %}
**Alert: Previously generated factors had errors in validation**
The error details are given as below:
{{ error_details }}
The next set of factors generated should be with respect to the error. For example, if the error logs say that no such function exists, then your goal is to generate the next set of factors without those functions.

Recommendations:
- Analyse the error and try to understand what caused the error.
- If a function does not exist, stop using that for new factor generation
- If there is syntax error, double check brackets, operator usage, division by zero errors.
{% endif %}

{% if expression_duplication %}
**Alert: Duplication Detected in Previous Factor Expressions**
{{ expression_duplication }}

Recommendations:
- Avoid the duplicated sub-expressions above
- Generate novel factor by uniquely combining data variables and operations
- Experiment with a mix of mathematical operations (e.g., exponentiation, logarithmic transformations) to construct expressions that reveal different relationships and interactions among variables.
- Replace raw variables with transformed variants to enhance expressiveness, such as using `$open`, `$close/TS_MEAN($close, 10)`, or `($open + $close) / 2` instead of `$close` to normalize or adjust for trends.
{% endif %}

Please generate the new {{targets}} in JSON format based on the information above.
"""

OUTPUT_FORMAT = """**CRITICAL: OUTPUT ONLY VALID JSON - NO EXPLANATIONS OR COMMENTARY**

Do NOT use any undeclared variables. The factor expression should be strictly based on the function library (e.g. `RANK(.)`) and the variables provided in data (e.g., `$open`).

Your response must be ONLY the JSON object below with NO additional text before or after.
Do NOT include explanations, reasoning, or commentary.
Do NOT start with "Here is the JSON..." or similar preamble.
Output ONLY valid JSON that starts with { and ends with }.

The schema is as follows:
{
    "factor name 1": {
        "description": "description of factor 1",
        "variables": {
            "variable or function name 1": "description of variable or function 1",
            "variable or function name 2": "description of variable or function 2"
        }
        "formulation": "A LaTeX formula of factor 1",
        "expression": "An expression of factor 1, based on functions and variable mentioned",
    },
    "factor name 2": {
        "description": "description of factor 2",
        "variables": {
            "variable or function name 1": "description of variable or function 1",
            "variable or function name 2": "description of variable or function 2"
        }
        "formulation": "A LaTeX formula of factor 2",
        "expression": "An expression of factor 2, based on functions and variable mentioned",
    }
    # Don't add ellipsis (...) or any filler text that might cause JSON parsing errors here!
}

Here is an example:
{
    "Normalized_Intraday_Range_Factor_10D": {
        "description": "This factor integrates candlestick movement patterns with market volatility to enhance predictive accuracy for short-term price movements. The factor computes the normalized difference between the candlestick body size and the standard deviation of closing prices over a 10-day period.",
        "variables": {
            "$close": "Close price of the stock on that day.",
            "$open": "Open price of the stock on that day.",
            "ABS(A)": "Absolute value of A.",
            "TS_STD(A, n)": "Standard deviation of sequence A over the past n days."
        },
        "formulation": "NIR_{10D} = \\frac{|close - open|}{TS\\_STD(close, 10) + \\epsilon}",
        "expression": "ABS($close - $open) / (TS_STD($close, 10) + 1e-8)"
    },
    "Volume_Range_Correlation_Factor_20D": {
        "description": "This factor measures the correlation between the candlestick range (high - low) and the trading volume over a 20-day period, aiming to capture the relationship between price range and market participation.",
        "variables": {
            "$high": "High price of the stock on that day.",
            "$low": "Low price of the stock on that day.",
            "$volume": "Volume of the stock on that day.",
            "TS_CORR(A, B, n)": "Correlation coefficient between sequences A and B over the past n days."
        },
        "formulation": "VRC_{20D} = TS\\_CORR(high - low, volume, 20)",
        "expression": "TS_CORR($high - $low, $volume, 20)"
    }
}"""

# ============================================================================
# NODE FUNCTION
# ============================================================================

def factor_construct(state: WorkflowState, llm, node_number: str = "02") -> dict[str, Any]:
    """
    Construct factors based on hypothesis.
    
    Inputs:
        - state['hypothesis']: Hypothesis object from factor_propose
        - state['trace']: Trace object with previous experiments
    
    Outputs:
        - Returns dict with 'experiment': Experiment object with sub_tasks (2-3 factors)
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    recorder = state.get("recorder")
    logger = create_recorder_logger(recorder)
    iteration = state.get("_mlflow_iteration", 0)

    node_tag = f"{node_number}_factor_construct"
    with logger.tag(f"iter_{iteration}.{node_tag}"):
        logger.info("Starting factor construction")

        trace = state.get("trace")
        hypothesis = state.get("hypothesis")

        # Build hypothesis and feedback history string
        hypothesis_and_feedback = (
            (
                Environment(undefined=StrictUndefined)
                .from_string(HYPOTHESIS_AND_FEEDBACK_TEMPLATE)
                .render(trace=trace)
            )
            if len(trace.hist) > 0
            else "No previous hypothesis and feedback available since it's the first round."
        )

        # Extract previous experiments and factors
        experiment_list = [t[1] for t in trace.hist]
        factor_list = []
        for experiment in experiment_list:
            factor_list.extend(experiment.sub_tasks)

        # Build messages
        messages = []
        messages.append(SystemMessage(
            Environment(undefined=StrictUndefined)
            .from_string(SYSTEM_PROMPT)
            .render(
                targets="factors",
                scenario=SCENARIO_DESCRIPTION,
                experiment_output_format=OUTPUT_FORMAT,
            )
        ))
        if state.get("validation_error", False):
            error_details = state.get("agent_logs")[-1]
        else:
            error_details = None
        messages.append(HumanMessage(
            Environment(undefined=StrictUndefined)
            .from_string(USER_PROMPT)
            .render(
                targets="factors",
                target_hypothesis=hypothesis_string(hypothesis),
                hypothesis_and_feedback=hypothesis_and_feedback,
                function_lib_description=FUNCTION_LIBRARY,
                target_list=factor_list,
                expression_duplication=None,  # No duplication checking for now
                validation_error=state.get("validation_error", False),
                error_details=error_details
            )
        ))

        # Get LLM response
        logger.info("Calling LLM for factor construction...")

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

        # Extract JSON from response (handle various formats)
        response_content = response_content.strip()

        # Try to extract JSON from markdown code fences
        if '```json' in response_content or '```' in response_content:
            import re
            json_match = re.search(r'```(?:json)?\s*\n(.*?)\n```', response_content, re.DOTALL)
            if json_match:
                response_content = json_match.group(1).strip()
                logger.info("Extracted JSON from markdown code fences")
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
            # Look for JSON object in the response - find first { to last }
            json_match = re.search(r'\{.*\}', response_content, re.DOTALL)
            if json_match:
                response_content = json_match.group(0)
                logger.info("Extracted JSON object from LLM commentary")

        # Parse JSON with error handling
        try:
            response_dict = json.loads(response_content)
        except json.JSONDecodeError as e:
            logger.warning(f"JSON parse error: {e}. Attempting to fix escape sequences...")
            # Replace all single backslashes with double backslashes
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

        # Create FactorTask objects from response
        # Expected format: {factor_name: {description, variables, formulation, expression}, ...}
        sub_tasks = []

        for factor_name, factor_data in response_dict.items():
            if isinstance(factor_data, dict):
                logger.info(f"Processing factor '{factor_name}' with fields: {list(factor_data.keys())}")

                factor_task = FactorTask(
                    name=factor_name,
                    description=factor_data.get("description", ""),
                    expression=factor_data.get("expression", ""),
                    formulation=factor_data.get("formulation", ""),
                    variables=factor_data.get("variables", {}),
                )
                sub_tasks.append(factor_task)

        # Create Experiment object
        experiment = Experiment(
            sub_tasks=sub_tasks,
            sub_workspace_list=[None] * len(sub_tasks),
            result=None,
            sub_results={},
            experiment_workspace=None,
        )

        logger.info(f"Generated {len(sub_tasks)} factors")
        for task in sub_tasks:
            logger.info(f"  - {task.name}: {task.expression}")

        log_generated_factors_to_mlflow(recorder, node_tag, sub_tasks, step=iteration)

        if recorder and recorder.active_run:
            try:
                recorder.log_metrics(step=iteration, factors_generated=float(len(sub_tasks)))
                recorder.log_metrics(factors_generated=float(len(sub_tasks)))
            except Exception:
                pass

        logger.flush()

        log_msg = f"{node_number}_factor_construct: built {len(experiment.sub_tasks)} factors at {datetime.now().isoformat()}"
        return {
            "experiment": experiment,
            "agent_logs": [log_msg],
            "_mlflow_llm_step": next_llm_step,
        }
