# MCP Integration Examples

This directory contains examples of integrating quant-stream with AI agents through the MCP (Model Context Protocol) server.

## Files

### `test_mcp_client.py`
Basic MCP client testing script that demonstrates all available tools:
- Health check
- List available tools
- Calculate factor
- Run backtest
- Run workflow

**Usage:**
```bash
# Start the MCP server first
python -m mcp_server

# In another terminal, run the tests
python examples/mcp_integration/test_mcp_client.py
```

### `agent_integration.py`
Example integration with AlphaCopilot workflow, showing:
- MCPClient class for easy interaction
- Integration with factor_calculate and factor_backtest nodes
- Example workflow state management

**Usage:**
```bash
# Start the MCP server first
python -m mcp_server

# Run the integration example
python examples/mcp_integration/agent_integration.py
```

## Quick Start

### 1. Start the MCP Server

```bash
# Option 1: Run directly
python -m mcp_server

# Option 2: Run with uvicorn
uvicorn mcp_server.server:app --host 0.0.0.0 --port 8080

# Option 3: Use Docker
cd mcp_server
docker-compose up
```

### 2. Test the Server

```bash
# Health check
curl http://localhost:8080/health

# List tools
curl http://localhost:8080/tools

# API docs
open http://localhost:8080/docs
```

### 3. Run Examples

```bash
# Test all MCP tools
python examples/mcp_integration/test_mcp_client.py

# Test AlphaCopilot integration
python examples/mcp_integration/agent_integration.py
```

## MCP Client Usage

### Basic Usage

```python
from examples.mcp_integration.agent_integration import MCPClient

# Create client
with MCPClient(base_url="http://localhost:8080") as client:
    # Calculate factor
    result = client.calculate_factor(
        expression="DELTA($close, 1)",
        factor_name="momentum",
        data_config={
            "path": ".data/indian_stock_market_nifty500.csv",
            "start_date": "2022-01-01",
            "end_date": "2022-12-31"
        }
    )
    print(f"Success: {result['success']}")
    print(f"Samples: {result['num_samples']}")
```

### Run Workflow (Backtest Included)

```python
with MCPClient() as client:
    result = client.run_workflow(
        config_dict={
            "data": {"path": ".data/indian_stock_market_nifty500.csv"},
            "features": [
                {"name": "momentum", "expression": "DELTA($close, 1)"}
            ],
            "model": None,
            "strategy": {
                "type": "TopkDropout",
                "params": {"topk": 30, "n_drop": 5}
            },
            "backtest": {
                "initial_capital": 1000000,
                "commission": 0.001,
                "slippage": 0.001
            },
            "experiment": {"name": "demo_workflow"}
        }
    )
    print(f"Sharpe Ratio: {result['metrics']['sharpe_ratio']:.2f}")
    print(f"Total Return: {result['metrics']['total_return']:.2%}")
```

### Run Complete Workflow

```python
with MCPClient() as client:
    result = client.run_workflow(
        config_path="examples/configs/basic_momentum.yaml",
        output_path="results/backtest.csv"
    )
    print(f"Success: {result['success']}")
    print(f"Experiment: {result['run_info']['experiment_name']}")
    print(f"Sharpe: {result['metrics']['sharpe_ratio']:.2f}")
```

## AlphaCopilot Integration

The MCP server is designed to integrate seamlessly with AlphaCopilot's workflow graph. Here's how to use it:

### 1. Update `alphacopilot/workflow_graph.py`

```python
from examples.mcp_integration.agent_integration import (
    MCPClient,
    factor_calculate_node,
    factor_backtest_node,
)

# Initialize MCP client (could be done at module level or passed in state)
mcp_client = MCPClient()

def factor_calculate(state: WorkflowState) -> dict[str, Any]:
    """Calculate factors using MCP server."""
    return factor_calculate_node(state, mcp_client)

def factor_backtest(state: WorkflowState) -> dict[str, Any]:
    """Run workflow (including backtest) using MCP server."""
    return factor_backtest_node(state, mcp_client)
```

### 2. State Structure

The MCP integration expects the following state structure:

```python
state = {
    "experiment": {
        "sub_tasks": [
            {
                "name": "factor_name",
                "expression": "FACTOR_EXPRESSION"
            }
        ]
    },
    "data_config": {
        "path": "path/to/data.csv",
        "start_date": "YYYY-MM-DD",
        "end_date": "YYYY-MM-DD"
    },
    "strategy": {
        "type": "TopkDropout",
        "params": {"topk": 30, "n_drop": 5}
    },
    "backtest": {
        "initial_capital": 1000000,
        "commission": 0.001,
        "slippage": 0.001
    }
}
```

### 3. Result Structure

After `factor_backtest_node`, the state will include:

```python
state["experiment"]["result"] = {
    "metrics": {
        "total_return": 0.15,
        "sharpe_ratio": 1.8,
        "max_drawdown": -0.12,
        # ... more metrics
    },
    "num_periods": 250
}
```

## Testing

### Unit Tests

```bash
# Test individual tools
pytest tests/mcp_server/test_tools.py

# Test server endpoints
pytest tests/mcp_server/test_server.py
```

### Integration Tests

```bash
# Start server in background
python -m mcp_server &
SERVER_PID=$!

# Run integration tests
python examples/mcp_integration/test_mcp_client.py

# Stop server
kill $SERVER_PID
```

## Deployment

### Development

```bash
# Run with auto-reload
uvicorn mcp_server.server:app --reload --host 0.0.0.0 --port 8080
```

### Production

```bash
# Using Docker Compose
cd mcp_server
docker-compose up -d

# Check logs
docker-compose logs -f

# Stop
docker-compose down
```

### Configuration

Environment variables:
```bash
export MCP_HOST="0.0.0.0"
export MCP_PORT="8080"
export MCP_WORKERS="4"
export MCP_LOG_LEVEL="INFO"
export QUANTSTREAM_DATA_PATH=".data/indian_stock_market_nifty500.csv"
export QUANTSTREAM_MLRUNS_PATH="sqlite:///mlruns.db"
```

## Troubleshooting

### Connection Errors

```python
try:
    with MCPClient() as client:
        result = client.calculate_factor(...)
except httpx.ConnectError:
    print("Server not running. Start with: python -m mcp_server")
```

### Timeout Errors

```python
# Increase timeout for long-running operations
client = MCPClient(timeout=300.0)  # 5 minutes
```

### Data Not Found

Ensure your data file exists at the configured path:
```bash
ls -la .data/indian_stock_market_nifty500.csv
```

## API Reference

See the full API documentation at http://localhost:8080/docs when the server is running.

### Endpoints

- `GET /health` - Health check
- `GET /tools` - List available tools
- `POST /tools/calculate_factor` - Calculate alpha factor
- `POST /tools/run_ml_workflow` - Run backtest/workflow
- `POST /tools/run_workflow` - Run complete workflow

### Response Codes

- `200` - Success
- `400` - Bad request (validation error or tool failure)
- `500` - Server error

## Next Steps

1. Customize the integration for your specific agent workflow
2. Add error handling and retry logic
3. Implement result caching if needed
4. Add authentication for production deployment
5. Set up monitoring and logging

