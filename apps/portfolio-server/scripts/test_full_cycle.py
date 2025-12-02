import subprocess
import time
import sys
import os

def run_command(command, cwd=None):
    print(f"Running: {command}")
    result = subprocess.run(command, shell=True, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error running command: {command}")
        print(result.stderr)
        return False
    print(result.stdout)
    return True

def main():
    base_dir = "/home/manav/dev_ws/Pathway-Inter-IIT/apps/portfolio-server"
    
    # 1. Reset DB
    print("\n--- Resetting DB ---")
    # We need to pipe 'y' to the reset command
    reset_cmd = f"echo 'y' | python3 scripts/reset_and_audit.py --reset"
    if not run_command(reset_cmd, cwd=base_dir):
        return

    # 2. Ensure Agent
    print("\n--- Ensuring Agent ---")
    if not run_command("python3 scripts/ensure_agent.py", cwd=base_dir):
        return

    # 3. Inject BUY Signal
    print("\n--- Injecting BUY Signal ---")
    if not run_command("python3 pipelines/nse/push_fake_signal.py --symbol RELIANCE --signal 1 --price 1546.30", cwd=base_dir):
        return

    # 4. Wait for BUY execution
    print("\n--- Waiting for BUY execution ---")
    time.sleep(5) # Wait for celery to pick up

    # 5. Inject SELL Signal
    print("\n--- Injecting SELL Signal ---")
    if not run_command("python3 pipelines/nse/push_fake_signal.py --symbol RELIANCE --signal -1 --price 1592.69", cwd=base_dir):
        return

    # 6. Wait for SELL execution
    print("\n--- Waiting for SELL execution ---")
    time.sleep(5)

    # 7. Check Status
    print("\n--- Checking Status ---")
    run_command("python3 scripts/reset_and_audit.py --status", cwd=base_dir)
    
    # 8. Check Logs for Latency
    print("\n--- Checking Logs for Latency ---")
    run_command("python3 scripts/check_logs.py", cwd=base_dir)

if __name__ == "__main__":
    main()
