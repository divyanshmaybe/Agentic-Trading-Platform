"""Command-line interface for quant-stream."""

import sys
from pathlib import Path
from typing import Optional
import fire

from quant_stream.workflows import run_from_yaml
from quant_stream.config import load_config, save_config, get_default_config


class QuantStreamCLI:
    """Command-line interface for quant-stream workflows."""
    
    def run(
        self,
        config: str,
        output: Optional[str] = None,
        verbose: bool = True,
    ) -> None:
        """Run workflow from YAML configuration.
        
        Args:
            config: Path to YAML configuration file
            output: Optional path to save results CSV
            verbose: Whether to print progress messages (default: True)
            
        Example:
            quant-stream run --config workflow.yaml --output results.csv
        """
        try:
            results = run_from_yaml(config, output_path=output, verbose=verbose)
            
            if verbose:
                print("\n✓ Workflow completed successfully!")
                if results.get("metrics"):
                    print(f"  Sharpe Ratio: {results['metrics']['sharpe_ratio']:.2f}")
                    print(f"  Total Return: {results['metrics']['total_return']:.2%}")
        
        except Exception as e:
            print(f"\n✗ Error: {e}", file=sys.stderr)
            sys.exit(1)
    
    def validate(self, config: str) -> None:
        """Validate a YAML configuration file.
        
        Args:
            config: Path to YAML configuration file
            
        Example:
            quant-stream validate --config workflow.yaml
        """
        try:
            cfg = load_config(config)
            print(f"✓ Configuration is valid: {config}")
            print(f"  Data: {cfg.data.path}")
            print(f"  Features: {len(cfg.features)}")
            print(f"  Model: {cfg.model.type if cfg.model else 'None'}")
            print(f"  Strategy: {cfg.strategy.type}")
            
        except Exception as e:
            print(f"✗ Configuration is invalid: {e}", file=sys.stderr)
            sys.exit(1)
    
    def init(self, output: str = "workflow.yaml", force: bool = False) -> None:
        """Initialize a new configuration file with defaults.
        
        Args:
            output: Output path for configuration file (default: workflow.yaml)
            force: Overwrite existing file (default: False)
            
        Example:
            quant-stream init --output my_workflow.yaml
        """
        output_path = Path(output)
        
        if output_path.exists() and not force:
            print(f"✗ File already exists: {output}", file=sys.stderr)
            print("  Use --force to overwrite", file=sys.stderr)
            sys.exit(1)
        
        try:
            # Create default config
            from quant_stream.config import WorkflowConfig
            default_dict = get_default_config()
            config = WorkflowConfig(**default_dict)
            
            # Save to file
            save_config(config, output_path)
            
            print(f"✓ Created configuration file: {output}")
            print(f"  Edit the file and run: quant-stream run --config {output}")
            
        except Exception as e:
            print(f"✗ Error creating configuration: {e}", file=sys.stderr)
            sys.exit(1)
    
    def serve(
        self,
        celery_queue: str = "workflow",
        celery_workers: int = 4,
        celery_log_level: str = "info",
        redis_host: str = "localhost",
        redis_port: int = 6379,
        foreground: bool = True,
    ) -> None:
        """Start MCP server and Celery worker together.
        
        This command starts both the Celery worker (for background job processing)
        and provides instructions for connecting to the MCP server. The MCP server
        itself is typically started by clients via stdio, but this ensures the
        Celery backend is ready.
        
        Args:
            celery_queue: Celery queue name (default: workflow)
            celery_workers: Number of Celery worker processes (default: 1)
            celery_log_level: Celery log level (default: info)
            redis_host: Redis host for Celery broker (default: localhost)
            redis_port: Redis port for Celery broker (default: 6379)
            foreground: Run in foreground (default: True). If False, daemonize.
            
        Example:
            # Start both services
            quant-stream serve
            
            # Start with custom queue and workers
            quant-stream serve --celery_queue backtest --celery_workers 4
        """
        import subprocess
        import signal
        import sys
        import time
        import threading
        
        processes: list[tuple[str, subprocess.Popen]] = []
        monitor_threads: list[threading.Thread] = []
        
        def cleanup(signum=None, frame=None):
            """Clean up all child processes."""
            print("\n🛑 Shutting down services...")
            for name, proc in reversed(processes):
                if proc.poll() is not None:
                    continue
                try:
                    proc.terminate()
                    proc.wait(timeout=5)
                    print(f"  ✓ {name} stopped")
                except subprocess.TimeoutExpired:
                    proc.kill()
                    print(f"  ✓ {name} killed")
                except Exception as e:
                    print(f"  ⚠ Error stopping {name}: {e}")
            sys.exit(0)
        
        # Register signal handlers
        signal.signal(signal.SIGINT, cleanup)
        signal.signal(signal.SIGTERM, cleanup)
        
        try:
            # Check Redis connection
            try:
                import redis
                r = redis.Redis(host=redis_host, port=redis_port, socket_connect_timeout=2)
                r.ping()
                print(f"✓ Redis connected at {redis_host}:{redis_port}")
            except Exception as e:
                print(f"✗ Error: Cannot connect to Redis at {redis_host}:{redis_port}")
                print(f"  {e}")
                print("\nPlease start Redis first:")
                print("  brew services start redis  # macOS")
                print("  redis-server               # Linux")
                sys.exit(1)
            
            print("=" * 80)
            print("Starting Quant-Stream Services")
            print("=" * 80)
            print(f"Redis: {redis_host}:{redis_port}")
            print(f"Celery Queue: {celery_queue}")
            print(f"Celery Workers: {celery_workers}")
            print("=" * 80)
            print()
            
            # Start Celery worker
            print("🚀 Starting Celery worker...")
            celery_cmd = [
                sys.executable, "-u", "-m", "celery",  # -u flag makes Python unbuffered
                "-A", "quant_stream.mcp_server.core.celery_config:celery_app",
                "worker",
                "--loglevel", celery_log_level,
                "-Q", celery_queue,
                "--concurrency", str(celery_workers),
            ]
            
            celery_proc = subprocess.Popen(
                celery_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            processes.append(("Celery worker", celery_proc))
            print(f"  ✓ Celery worker started (PID: {celery_proc.pid})")
            print()
            
            # Print connection info
            print("=" * 80)
            print("Celery Worker Ready!")
            print("=" * 80)
            print()
            print("Celery Worker:")
            print(f"  - Queue: {celery_queue}")
            print(f"  - Workers: {celery_workers}")
            print(f"  - PID: {celery_proc.pid}")
            print()
            print("🌐 Starting MCP server (HTTP)...")
            mcp_cmd = [
                sys.executable,
                "-m",
                "quant_stream.mcp_server",
            ]
            mcp_proc = subprocess.Popen(
                mcp_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            processes.append(("MCP server", mcp_proc))
            print(f"  ✓ MCP server started (PID: {mcp_proc.pid})")
            print()
            print("  MCP Server listening at:")
            print("  - Host: 127.0.0.1")
            print("  - Port: 6969")
            print("  - Endpoint: http://127.0.0.1:6969/mcp")
            print()
            print("Clients can connect via:")
            print("  alphacopilot run \"hypothesis\" --backend mcp --mcp_server http://127.0.0.1:6969/mcp")
            print()
            print("Press Ctrl+C to stop services")
            print("=" * 80)
            print()
            
            # Monitor Celery process and output logs
            def _monitor_process(name: str, proc: subprocess.Popen):
                suppress_output = name == "MCP server"
                if proc.stdout:
                    for line in iter(proc.stdout.readline, ''):
                        if line:
                            if suppress_output:
                                continue
                            print(f"[{name}] {line.rstrip()}")
            
            for name, proc in processes:
                monitor_thread = threading.Thread(
                    target=_monitor_process,
                    args=(name, proc),
                    daemon=True,
                )
                monitor_thread.start()
                monitor_threads.append(monitor_thread)
            
            # Wait for processes
            while True:
                for name, proc in processes:
                    if proc.poll() is not None:
                        print(f"\n✗ {name} exited with code {proc.returncode}")
                        cleanup()
                time.sleep(1)
                
        except KeyboardInterrupt:
            cleanup()
        except Exception as e:
            print(f"\n✗ Error: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            cleanup()
            sys.exit(1)
    
    def version(self) -> None:
        """Show quant-stream version.
        
        Example:
            quant-stream version
        """
        try:
            import importlib.metadata
            version = importlib.metadata.version("quant-stream")
            print(f"quant-stream version {version}")
        except Exception:
            print("quant-stream (version unknown)")


def main():
    """Main entry point for CLI."""
    fire.Fire(QuantStreamCLI)


if __name__ == "__main__":
    main()
