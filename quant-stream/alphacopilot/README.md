## AlphaCopilot LangGraph Workflow

A standalone implementation of the AlphaCopilot factor mining workflow using LangGraph and MCP server integration.

### Overview

This implementation provides:
- **LangGraph workflow** for automated factor discovery and evaluation
- **Trace system** for tracking hypothesis → experiment → feedback iterations
- **MCP server integration** via `langchain-mcp-adapters` for factor calculation and backtesting
- **Logging system** inspired by AlphaCopilot's hierarchical logging

### Architecture

```
factor_propose → factor_construct → factor_validate → factor_workflow → feedback
     ↓               ↓                    ↓                  ↓              ↓
 Hypothesis      Experiment          Validation       Run Workflow      Feedback
                (2-3 factors)   (via MCP parser)    (via MCP async)  + Trace Update
```

**Key Concept**: The agent generates **only factor expressions**. Everything else (data, strategy, model, backtest parameters) is pre-configured in `workflow_config`. The `factor_workflow` step runs the complete workflow with agent-generated factors.

### Key Components

1. **graph.py** - LangGraph workflow construction and compilation
2. **nodes/** - Modular node implementations (each contains node function + prompts)
   - **factor_propose.py** - Generate market hypothesis
   - **factor_construct.py** - Construct factors based on hypothesis
   - **factor_validate.py** - Validate factor expressions
   - **factor_workflow.py** - Run ML workflow with MCP server
   - **feedback.py** - Generate feedback on results
3. **types.py** - Data structures (Hypothesis, Experiment, Trace, etc.)
4. **state.py** - LangGraph state schema
5. **logger.py** - Hierarchical logging system
6. **mcp_client.py** - MCP server client using langchain-mcp-adapters
7. **scenario.py** - Scenario definitions and descriptions
8. **MCP_TOOLS_EXPLAINED.md** - Detailed explanation of MCP tools (backtest vs ML workflow)

### Usage

#### Command-Line Interface (Recommended)

The easiest way to use AlphaCopilot is through the CLI:

```bash
# Run AlphaCopilot with the default library backend (synchronous)
alphacopilot run "Short-term momentum predicts future returns" \
  --model_type LightGBM \
  --data_path .data/indian_stock_market_nifty500.csv \
  --symbols_file .data/nifty500.txt \
  --train_start_date 2021-06-01 \
  --train_end_date 2021-12-01 \
  --test_start_date 2021-12-01 \
  --test_end_date 2021-12-31 \
  --max_iterations 3

# Run using workflow API (high-level, maintainable)
alphacopilot run "Volume predicts returns" \
  --backend binary \
  --symbols_file .data/nifty500.txt \
  --model_type LightGBM \
  --train_start_date 2021-06-01 \
  --train_end_date 2021-12-01 \
  --test_start_date 2021-12-01 \
  --test_end_date 2021-12-31 \
  --max_iterations 3

# Run using direct library (low-level, fastest)
alphacopilot run "Volume predicts returns" \
  --backend library \
  --symbols_file .data/nifty500.txt \
  --model_type LightGBM

# Using MCP server (async, distributed)
alphacopilot run "Volume predicts returns" \
  --backend mcp \
  --mcp_server "http://custom-host:8000/mcp" \
  --symbols_file .data/nifty500.txt \
  --model_type LightGBM

# Using custom MCP server via stdio (script)
alphacopilot run "Volume predicts returns" \
  --backend mcp \
  --mcp_server "./my_server.py" \
  --symbols_file .data/nifty500.txt \
  --model_type LightGBM

# Validate a factor expression
alphacopilot validate --factor_expression "RANK(DELTA(\$close, 5))"

# List all available functions
alphacopilot list-functions

# Show version
alphacopilot version

# Start REST API server
alphacopilot server

# Start server on custom port
alphacopilot server --port 9000

# Start server with auto-reload (development)
alphacopilot server --reload

# Get help
alphacopilot --help
alphacopilot run --help
alphacopilot server --help
```

**Execution Backends:**

All backends have **full feature parity** - they use the same underlying functions with different execution modes:

| Backend | Execution | Use Case | Setup Required |
|---------|-----------|----------|----------------|
| `library` (default) | Sync direct functions | Fastest iteration, development | None |
| `binary` | Sync workflow runner | Stable API, reproducible runs | None |
| `mcp` | Async via MCP server + Celery | Production, distributed | MCP server (stdio or SSE) + Redis |

#### Execution Modes Explained

**Synchronous Execution** (`library` and `binary` backends):
- Workflow runs **immediately** and **blocks** until complete
- Returns results **directly** (no job_id)
- Tool has `execution_mode = "sync"` attribute
- Detected by `factor_workflow` node via `hasattr(tool, "execution_mode")`
- Best for: CLI usage, debugging, single-machine runs

**Asynchronous Execution** (`mcp` backend with Celery):
- Workflow **submits job** and returns immediately with `job_id`
- Results retrieved by **polling** `check_job_status` with the job_id
- Supports progress updates during execution
- Requires: Celery worker + Redis/RabbitMQ broker
- Best for: Production, distributed systems, web APIs

**MCP Fallback Mode** (when Celery not available):
- MCP server falls back to synchronous execution if Celery not installed
- Returns `{"job_id": "mcp_sync_fallback", "status": "SUCCESS", "result": {...}}`
- Allows MCP server to work without Celery (development mode)

**MCP Server Connection Options:**

The `--mcp_server` flag supports multiple connection types with auto-detection:

| Connection Type | Example | Transport | Use Case |
|----------------|---------|-----------|----------|
| Default (HTTP) | _(omit flag)_ | HTTP/mcp | Default: `http://127.0.0.1:6969/mcp` |
| Custom HTTP | `http://custom-host:8000/mcp` | HTTP/mcp | Remote server, production |
| Custom stdio script | `./my_server.py` | stdio | Local script-based server |

**Note:** The `fastmcp` package is now a required dependency and supports all connection types (stdio, SSE, in-memory) with auto-detection.

**All backends support:**
- ✅ All factor expressions
- ✅ All model types (LightGBM, XGBoost, etc.)
- ✅ All strategy configurations
- ✅ All data filtering options
- ✅ Custom factors
- ✅ Iterative feedback

Choose based on your deployment needs, not features!

**Note:** The `hypothesis` parameter is **mandatory** for the `run` command. The agent will generate factors based on your hypothesis and iteratively refine them based on backtest results.

#### Programmatic Usage

You can also use AlphaCopilot programmatically in Python:

```python
import asyncio
from alphacopilot.graph import create_workflow_graph
from alphacopilot.types import WorkflowState
from alphacopilot.mcp_client import create_mcp_tools

async def run_alphacopilot():
    # Load MCP tools
    mcp_tools = await create_mcp_tools()
    
    # Build workflow configuration
    workflow_config = {
        # Data configuration
        "data_path": ".data/indian_stock_market_nifty500.csv",
        "data_start_date": "2021-01-01",  # Filters data during loading (performance optimization)
        "data_end_date": "2021-12-31",    # Use earliest train and latest test date
        
        # Model configuration
        "model_type": "LightGBM",
        "model_params": {},
        
        # Strategy configuration
        "strategy_type": "TopkDropout",
        "strategy_method": "equal",
        "topk": 30,
        "n_drop": 5,
        
        # Backtest configuration (train/test split)
        "backtest_train_dates": ["2021-01-01", "2021-06-30"],
        "backtest_test_dates": ["2021-07-01", "2021-12-31"],
        "initial_capital": 1_000_000,
        "commission": 0.001,
        "slippage": 0.001,
        "rebalance_frequency": 1,
        
        # Experiment configuration
        "experiment_name": "alphacopilot_workflow",
        "run_name": "momentum_test",
    }
    
    # Create initial state
    initial_state = WorkflowState(
        trace=Trace(),
        hypothesis=None,
        experiment=None,
        feedback=None,
        potential_direction="Short-term momentum predicts returns",
        mcp_tools=mcp_tools,
        workflow_config=workflow_config,
        custom_factors=[],  # Optional: add your own factor expressions
        max_iterations=3,
        stop_on_sota=False,
    )
    
    # Create and run workflow
    graph = create_workflow_graph()
    result = graph.invoke(initial_state)
    
    # Access results
    if result.get("results"):
        metrics = result["results"]["metrics"]
        print(f"Sharpe Ratio: {metrics['sharpe_ratio']:.2f}")
        print(f"Total Return: {metrics['total_return']:.2%}")

# Run async function
asyncio.run(run_alphacopilot())
```

### MCP Server Integration

The workflow integrates with the quant-stream MCP server using `langchain-mcp-adapters`:

```python
from alphacopilot.mcp_client import QuantStreamMCPClient

# Initialize client
async with QuantStreamMCPClient() as client:
    # Load tools
    tools = await client.get_tools()
    
    # Available MCP tools:
    # - validate_factors: Validate expression syntax
    # - run_ml_workflow: Unified workflow tool (with/without ML model)
    # - check_job_status: Poll for job completion
    # - cancel_background_job: Cancel running jobs
```

**Note**: Use `run_ml_workflow()` (unified workflow) or `Backtester().run()` for library integrations; the MCP server exposes only the unified workflow tool.

#### Workflow Configuration

The agent generates **only factor expressions**. All other parameters are pre-configured:

```python
workflow_config = {
    # Data (data_start/end_date filter during loading for performance)
    "data_path": ".data/indian_stock_market_nifty500.csv",
    "data_start_date": "2021-01-01",  # Filter data during loading
    "data_end_date": "2021-12-31",    # Use earliest train and latest test date
    
    # Model (None = use factors directly as signals)
    "model_type": None,  # or "LightGBM", "XGBoost", "Linear"
    "model_params": {},  # e.g., {"n_estimators": 100}
    
    # Strategy
    "strategy_type": "TopkDropout",
    "strategy_method": "equal",
    "topk": 30,
    "n_drop": 5,
    
    # Backtest - separate train/test periods
    "backtest_train_dates": ["2021-01-01", "2021-06-30"],
    "backtest_test_dates": ["2021-07-01", "2021-12-31"],
    "initial_capital": 1_000_000,
    "commission": 0.001,
    "slippage": 0.001,
    "rebalance_frequency": 1,
    
    # Experiment
    "experiment_name": "alphacopilot_workflow",
    "run_name": "test_run",
}

# Agent generates: [{"name": "momentum", "expression": "DELTA($close, 20)"}]
# Workflow runs with these factors + above config
```

**Performance Tip:**
- `data_start_date` and `data_end_date` filter the CSV data **during loading** (before any computation)
- Set these to your earliest train date and latest test date for optimal performance
- The CLI automatically calculates these from `--train_start_date` and `--test_end_date`
- This prevents loading unnecessary historical data that won't be used in backtesting

#### Async Job Pattern

The workflow tool follows an async job pattern:

1. **Submit**: Call `run_ml_workflow` tool → returns `job_id`
2. **Poll**: Call `check_job_status` with `job_id` → returns status
3. **Complete**: When status is `SUCCESS` → extract results

```python
# Submit job
submit_result = await workflow_tool.ainvoke({
    "factor_expressions": [...],  # Agent-generated
    **workflow_config,  # Pre-configured
})
job_id = submit_result["job_id"]

# Poll until complete
while True:
    status = await status_tool.ainvoke({"job_id": job_id})
    if status["status"] == "SUCCESS":
        result = status["result"]
        break
    time.sleep(5)
```

### Trace System

The trace system tracks the evolution of hypotheses and experiments:

```python
from alphacopilot.types import Trace

trace = Trace(hist=[], scen=None, knowledge_base=None)

# After each iteration, trace.hist contains:
# [(hypothesis_1, experiment_1, feedback_1), ...]

# Get state-of-the-art (best) result
sota_hypothesis, sota_experiment = trace.get_sota_hypothesis_and_experiment()
```

### Logging & MLflow

AlphaCopilot now reuses the shared quant-stream `Recorder` for experiment tracking.
Use `alphacopilot.recorder_utils.create_recorder_logger` during node execution to
print console logs and persist artifacts (LLM transcripts, JSON snapshots,
DataFrames) to MLflow:

```python
from alphacopilot.recorder_utils import create_recorder_logger

logger = create_recorder_logger(recorder)  # recorder = quant_stream.recorder.Recorder

with logger.tag("02_factor_construct"):
    logger.info("Generating factors...")
    logger.log_json("factors", factor_payload)
```

### REST API Server

AlphaCopilot includes a built-in REST API server for programmatic access:

```bash
# Start the server
alphacopilot server

# Server will be available at http://localhost:8069
# API documentation at http://localhost:8069/docs
```

**API Endpoints:**
- `POST /runs` - Create new workflow runs
- `GET /runs` - List all runs
- `GET /runs/{run_id}` - Get run details
- `GET /runs/{run_id}/status` - Poll run status (with long polling)
- `GET /runs/{run_id}/results` - Get completed run results
- `DELETE /runs/{run_id}` - Cancel a run

See the server README for detailed API documentation.

### Requirements

- Python 3.11+
- LangGraph
- langchain-mcp-adapters
- fastmcp (for MCP connections with auto-detection)
- FastAPI, Uvicorn (for REST API server)
- SQLAlchemy (for run storage)
- LLM API access (OpenAI, Anthropic, Groq, etc.)
- quant-stream (for all backends)

**Installation:**
```bash
# Install alphacopilot (includes all dependencies)
uv pip install -e alphacopilot

# Or from workspace root
uv sync --all-groups --all-packages
```

### Environment Setup

Create `.env` file:

```bash
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=your_api_key_here
LLM_MODEL_NAME=gpt-4
```

### Differences from Original AlphaCopilot

1. **Simplified Code Generation**: Uses MCP workflow tool instead of CoSTEER iterative refinement
2. **MCP Integration**: Uses langchain-mcp-adapters for tool loading
3. **Standalone**: No dependencies on original alphacopilot package
4. **LangGraph**: Uses LangGraph for workflow orchestration
5. **Unified Workflow**: Single `run_ml_workflow` tool for all scenarios
6. **Agent Focus**: Agent generates ONLY factors; all other params pre-configured
7. **Async Pattern**: Job submission + polling instead of blocking execution

### References

- Workflow reference: `alphacopilot/components/workflow/alphacopilot_loop.py`
- Prompts reference: `alphacopilot/scenarios/qlib/prompts_alphacopilot.yaml`

