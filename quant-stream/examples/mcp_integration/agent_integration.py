"""Example AlphaCopilot integration with MCP server.

This demonstrates how to integrate the MCP server with AlphaCopilot's workflow.
"""

import httpx
from typing import Dict, Any, Optional


class MCPClient:
    """Client for interacting with Quant-Stream MCP Server."""
    
    def __init__(self, base_url: str = "http://localhost:8080", timeout: float = 180.0):
        """Initialize MCP client.
        
        Args:
            base_url: Base URL of MCP server
            timeout: Request timeout in seconds
        """
        self.base_url = base_url
        self.timeout = timeout
        self.client = httpx.Client(timeout=timeout)
    
    def calculate_factor(
        self,
        expression: str,
        factor_name: str,
        data_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Calculate alpha factor from expression.
        
        Args:
            expression: Factor expression (e.g., 'DELTA($close, 1)')
            factor_name: Name for the output factor
            data_config: Optional data configuration
            
        Returns:
            Response dictionary with success, factor_name, num_samples, etc.
        """
        response = self.client.post(
            f"{self.base_url}/tools/calculate_factor",
            json={
                "expression": expression,
                "factor_name": factor_name,
                "data_config": data_config,
            }
        )
        response.raise_for_status()
        return response.json()
    
    def run_workflow(
        self,
        config_path: Optional[str] = None,
        config_dict: Optional[Dict[str, Any]] = None,
        output_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run complete workflow.
        
        Args:
            config_path: Path to YAML config (or config_dict)
            config_dict: Configuration dictionary (or config_path)
            output_path: Optional path to save results
            
        Returns:
            Response dictionary with success, metrics, run_info, etc.
        """
        response = self.client.post(
            f"{self.base_url}/tools/run_workflow",
            json={
                "config_path": config_path,
                "config_dict": config_dict,
                "output_path": output_path,
            }
        )
        response.raise_for_status()
        return response.json()
    
    def close(self):
        """Close the client."""
        self.client.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        self.close()


# ============================================================================
# AlphaCopilot Workflow Integration
# ============================================================================

def factor_calculate_node(state: Dict[str, Any], mcp_client: MCPClient) -> Dict[str, Any]:
    """AlphaCopilot factor_calculate node implementation using MCP.
    
    This replaces the CoSTEER iterative code generation approach with
    a direct tool call to the MCP server.
    
    Args:
        state: Workflow state with experiment containing factor expressions
        mcp_client: MCP client instance
        
    Returns:
        Updated state with calculated factor values
    """
    experiment = state.get("experiment")
    
    if not experiment or not experiment.get("sub_tasks"):
        return {"experiment": experiment}
    
    # Extract factor expressions from sub_tasks
    factor_expressions = []
    for task in experiment["sub_tasks"]:
        factor_expressions.append({
            "name": task["name"],
            "expression": task["expression"]
        })
    
    # Calculate factors using MCP
    try:
        result = mcp_client.calculate_factor(
            expression=factor_expressions[0]["expression"],
            factor_name=factor_expressions[0]["name"],
            data_config=state.get("data_config"),
        )
        
        if result["success"]:
            # Update experiment with calculated factors
            experiment["factor_calculated"] = True
            experiment["num_samples"] = result["num_samples"]
        else:
            experiment["error"] = result.get("error")
    
    except Exception as e:
        experiment["error"] = str(e)
    
    return {"experiment": experiment}


def factor_backtest_node(state: Dict[str, Any], mcp_client: MCPClient) -> Dict[str, Any]:
    """AlphaCopilot factor_backtest node implementation using MCP.
    
    Args:
        state: Workflow state with experiment containing calculated factors
        mcp_client: MCP client instance
        
    Returns:
        Updated state with backtest results
    """
    experiment = state.get("experiment")
    
    if not experiment or not experiment.get("sub_tasks"):
        return {"experiment": experiment}
    
    # Extract factor expressions
    factor_expressions = []
    for task in experiment["sub_tasks"]:
        factor_expressions.append({
            "name": task["name"],
            "expression": task["expression"]
        })
    
    # Default strategy and backtest config
    strategy = state.get("strategy", {
        "type": "TopkDropout",
        "params": {"topk": 30, "n_drop": 5, "method": "equal"}
    })
    
    backtest = state.get("backtest", {
        "initial_capital": 1000000,
        "commission": 0.001,
        "slippage": 0.001,
    })
    
    # Run workflow using MCP with a unified config dict
    try:
        config_dict = {
            "data": state.get("data_config"),
            "features": factor_expressions,
            "model": None,
            "strategy": strategy,
            "backtest": backtest,
            "experiment": state.get("experiment_config", {"name": "alphacopilot_mcp_demo"}),
        }
        if not config_dict["data"]:
            config_dict["data"] = {"path": ".data/indian_stock_market_nifty500.csv"}

        result = mcp_client.run_workflow(config_dict=config_dict)

        if result["success"]:
            # Update experiment with backtest results
            experiment["result"] = {
                "metrics": result["metrics"],
            }
            experiment["sub_results"] = result["metrics"]
        else:
            experiment["error"] = result.get("error")
    
    except Exception as e:
        experiment["error"] = str(e)
    
    return {"experiment": experiment}


# ============================================================================
# Example Usage
# ============================================================================

def example_usage():
    """Example of using MCP client in AlphaCopilot workflow."""
    
    # Initialize MCP client
    with MCPClient() as client:
        # Example state from AlphaCopilot
        state = {
            "experiment": {
                "sub_tasks": [
                    {
                        "name": "momentum_factor",
                        "expression": "DELTA($close, 1)"
                    }
                ]
            },
            "data_config": {
                "path": ".data/indian_stock_market_nifty500.csv",
                "start_date": "2022-01-01",
                "end_date": "2022-03-31"
            },
            "strategy": {
                "type": "TopkDropout",
                "params": {"topk": 30, "n_drop": 5, "method": "equal"}
            },
            "backtest": {
                "initial_capital": 1000000,
                "commission": 0.001,
                "slippage": 0.001,
            }
        }
        
        # Execute factor calculation node
        print("Calculating factors...")
        state = factor_calculate_node(state, client)
        print(f"Result: {state['experiment']}")
        print()
        
        # Execute backtest node
        print("Running backtest...")
        state = factor_backtest_node(state, client)
        result_payload = state["experiment"].get("result")
        if result_payload:
            print(f"Result: {result_payload}")
        else:
            print(f"Result: {state['experiment']}")
        print()
        
        # Display metrics
        if result_payload:
            metrics = result_payload["metrics"]
            print("Backtest Metrics:")
            for key, value in metrics.items():
                if key.endswith('return') or key.endswith('drawdown'):
                    print(f"  {key}: {value:.2%}")
                else:
                    print(f"  {key}: {value:.4f}")


if __name__ == "__main__":
    print("=" * 80)
    print("AlphaCopilot MCP Integration Example")
    print("=" * 80)
    print()
    
    try:
        example_usage()
    except httpx.ConnectError:
        print("ERROR: Could not connect to MCP server.")
        print("Start the server: python -m mcp_server")
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()

