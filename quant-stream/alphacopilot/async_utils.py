"""
Async utilities for running async code from sync contexts.

This module provides helpers to properly run async code when called from
both sync and async contexts, avoiding the "asyncio.run() cannot be called
from a running event loop" error.
"""

import asyncio
from typing import Any, Coroutine, TypeVar
from concurrent.futures import ThreadPoolExecutor

T = TypeVar("T")

# Thread pool for running async code in sync context
_executor = ThreadPoolExecutor(max_workers=4)


def run_async(coro: Coroutine[Any, Any, T]) -> T:
    """
    Run an async coroutine from a sync context, handling the case where
    an event loop may already be running.
    
    This function will:
    1. If no event loop is running: use asyncio.run()
    2. If an event loop IS running: run the coroutine in a separate thread
       with its own event loop to avoid conflicts.
    
    Args:
        coro: The coroutine to run
        
    Returns:
        The result of the coroutine
    """
    try:
        # Check if there's a running event loop
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running loop, we can use asyncio.run() safely
        loop = None
    
    if loop is None:
        # No running event loop, use asyncio.run()
        return asyncio.run(coro)
    else:
        # There's already a running event loop, we need to run in a thread
        # to avoid "asyncio.run() cannot be called from a running event loop"
        import concurrent.futures
        
        def run_in_thread():
            # Create a new event loop for this thread
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            try:
                return new_loop.run_until_complete(coro)
            finally:
                new_loop.close()
        
        # Submit to thread pool and wait for result
        future = _executor.submit(run_in_thread)
        return future.result()
