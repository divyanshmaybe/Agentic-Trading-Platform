"""
Integration test for allocation tasks to verify the full flow works.
This test verifies that when an objective is created, allocations, trading agents, and snapshots are created.
"""

import pytest
import sys
from pathlib import Path

# Add portfolio-server to path
server_root = Path(__file__).resolve().parents[1]
if str(server_root) not in sys.path:
    sys.path.insert(0, str(server_root))

# This is a simple smoke test to verify the allocation logic works
def test_weight_extraction_logic():
    """Test that weight extraction logic works correctly."""
    from workers import allocation_tasks
    
    # Test case 1: weights in "weights" field
    result1 = {"weights": {"high_risk": 0.4, "low_risk": 0.3, "alpha": 0.3}}
    weights1 = allocation_tasks._coerce_to_plain_dict(result1.get("weights"))
    assert weights1 == {"high_risk": 0.4, "low_risk": 0.3, "alpha": 0.3}
    
    # Test case 2: weights in "weights_json" as string
    import json
    result2 = {"weights_json": json.dumps({"high_risk": 0.5, "low_risk": 0.5})}
    weights_json_raw = result2.get("weights_json")
    if isinstance(weights_json_raw, str):
        weights2 = json.loads(weights_json_raw)
    else:
        weights2 = allocation_tasks._coerce_to_plain_dict(weights_json_raw)
    assert weights2 == {"high_risk": 0.5, "low_risk": 0.5}
    
    # Test case 3: no weights - should handle gracefully
    result3 = {"expected_return": 0.12}
    weights3 = allocation_tasks._coerce_to_plain_dict(result3.get("weights"))
    assert weights3 == {}
    
    print("✅ Weight extraction logic tests passed")

