"""
File-based write lock utility.

Provides exclusive file locking for write operations.
Readers will wait/block until write lock is released.
"""

import fcntl
import os
import time
from pathlib import Path
from typing import Optional


class FileWriteLock:
    """
    Exclusive write lock for file operations.
    
    Blocks all file access (readers and writers) during updates.
    Uses fcntl (Linux) for file locking.
    
    Usage:
        with FileWriteLock(file_path):
            # Exclusive access - all readers blocked
            write_data()
    """

    def __init__(self, file_path: str | Path, timeout: Optional[float] = None):
        """
        Initialize write lock.
        
        Args:
            file_path: Path to the file to lock
            timeout: Maximum time to wait for lock (None = wait indefinitely)
        """
        self.file_path = Path(file_path)
        self.lock_file_path = self.file_path.parent / f".{self.file_path.name}.lock"
        self.timeout = timeout
        self.lock_file = None
        self.locked = False

    def __enter__(self):
        """Acquire exclusive write lock"""
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Release write lock"""
        self.release()

    def acquire(self):
        """Acquire exclusive write lock (blocking)"""
        if self.locked:
            return

        # Ensure lock file directory exists
        self.lock_file_path.parent.mkdir(parents=True, exist_ok=True)

        # Open lock file in append mode (create if doesn't exist)
        self.lock_file = open(self.lock_file_path, "a")

        start_time = time.time()

        while True:
            try:
                # Try to acquire exclusive lock (LOCK_EX = exclusive, LOCK_NB = non-blocking)
                # We use LOCK_EX for exclusive lock (blocks all access)
                fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.locked = True
                return

            except BlockingIOError:
                # Lock is held by another process
                if self.timeout is not None:
                    elapsed = time.time() - start_time
                    if elapsed >= self.timeout:
                        raise TimeoutError(
                            f"Failed to acquire lock for {self.file_path} after {self.timeout}s"
                        )

                # Wait a bit before retrying
                time.sleep(0.1)

    def release(self):
        """Release write lock"""
        if not self.locked:
            return

        if self.lock_file:
            try:
                fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass  # Ignore errors during release
            finally:
                self.lock_file.close()
                self.lock_file = None

        self.locked = False

        # Clean up lock file if it exists
        try:
            if self.lock_file_path.exists():
                self.lock_file_path.unlink()
        except Exception:
            pass  # Ignore cleanup errors


class FileReadLock:
    """
    Read lock that waits for write lock to release.
    
    This is a simple implementation that uses the same exclusive lock
    mechanism but is intended for read operations. In practice, for
    small JSON files, we can just read without a lock and let the
    write lock handle blocking.
    
    However, if you want to ensure no reads happen during writes,
    use this read lock which will wait for write locks to release.
    """

    def __init__(self, file_path: str | Path, timeout: Optional[float] = None):
        """
        Initialize read lock.
        
        Args:
            file_path: Path to the file to lock
            timeout: Maximum time to wait for lock (None = wait indefinitely)
        """
        self.file_path = Path(file_path)
        self.lock_file_path = self.file_path.parent / f".{self.file_path.name}.lock"
        self.timeout = timeout
        self.lock_file = None
        self.locked = False

    def __enter__(self):
        """Acquire read lock (waits for write lock to release)"""
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Release read lock"""
        self.release()

    def acquire(self):
        """Acquire read lock (waits for write lock to release)"""
        if self.locked:
            return

        # Ensure lock file directory exists
        self.lock_file_path.parent.mkdir(parents=True, exist_ok=True)

        # Open lock file in append mode
        self.lock_file = open(self.lock_file_path, "a")

        start_time = time.time()

        while True:
            try:
                # Try to acquire shared lock (LOCK_SH = shared, LOCK_NB = non-blocking)
                # Shared lock allows multiple readers but blocks if write lock is active
                fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
                self.locked = True
                return

            except BlockingIOError:
                # Lock is held by writer (exclusive lock)
                if self.timeout is not None:
                    elapsed = time.time() - start_time
                    if elapsed >= self.timeout:
                        raise TimeoutError(
                            f"Failed to acquire read lock for {self.file_path} after {self.timeout}s"
                        )

                # Wait for write lock to release
                time.sleep(0.1)

    def release(self):
        """Release read lock"""
        if not self.locked:
            return

        if self.lock_file:
            try:
                fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass  # Ignore errors during release
            finally:
                self.lock_file.close()
                self.lock_file = None

        self.locked = False

