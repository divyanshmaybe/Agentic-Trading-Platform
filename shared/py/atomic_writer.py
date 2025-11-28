"""
Atomic File Writer - Thread-safe file operations for concurrent access.

Prevents file corruption when multiple processes write to the same file.
"""

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Optional
import logging

logger = logging.getLogger(__name__)


class AtomicFileWriter:
    """
    Thread-safe, process-safe file writer using atomic operations.
    
    Uses:
    1. File locking (fcntl) to prevent concurrent writes
    2. Atomic rename for crash safety
    3. Proper error handling
    """
    
    def __init__(self, filepath: str, encoding: str = "utf-8"):
        self.filepath = Path(filepath)
        self.encoding = encoding
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
    
    @contextmanager
    def _file_lock(self, mode: str = "a"):
        """Context manager for file locking."""
        # Ensure file exists
        self.filepath.touch(exist_ok=True)
        
        fd = os.open(str(self.filepath), os.O_RDWR | os.O_CREAT)
        try:
            # Acquire exclusive lock (blocking)
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield fd
        finally:
            # Release lock
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
    
    def append_json(self, data: Dict[str, Any]) -> bool:
        """
        Atomically append a JSON object to a JSONL file.
        
        Uses file locking to prevent corruption from concurrent writes.
        """
        try:
            line = json.dumps(data, ensure_ascii=False) + "\n"
            
            with self._file_lock("a"):
                with open(self.filepath, "a", encoding=self.encoding) as f:
                    f.write(line)
                    f.flush()
                    os.fsync(f.fileno())  # Force write to disk
            
            return True
        except Exception as e:
            logger.error("Failed to append to %s: %s", self.filepath, e)
            return False
    
    def write_json(self, data: Dict[str, Any]) -> bool:
        """
        Atomically write a JSON object (overwrites file).
        
        Uses atomic rename for crash safety.
        """
        try:
            # Write to temp file first
            temp_fd, temp_path = tempfile.mkstemp(
                suffix=".tmp",
                dir=self.filepath.parent,
                text=True
            )
            
            try:
                with os.fdopen(temp_fd, "w", encoding=self.encoding) as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                
                # Atomic rename
                os.rename(temp_path, self.filepath)
                return True
                
            except Exception:
                # Clean up temp file on error
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
                raise
                
        except Exception as e:
            logger.error("Failed to write to %s: %s", self.filepath, e)
            return False
    
    def read_jsonl(self) -> list:
        """Read all lines from JSONL file."""
        if not self.filepath.exists():
            return []
        
        results = []
        with self._file_lock("r"):
            with open(self.filepath, "r", encoding=self.encoding) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            results.append(json.loads(line))
                        except json.JSONDecodeError:
                            logger.warning("Skipping invalid JSON line: %s", line[:50])
        
        return results


def atomic_jsonl_append(filepath: str, data: Dict[str, Any]) -> bool:
    """Convenience function for appending to JSONL atomically."""
    writer = AtomicFileWriter(filepath)
    return writer.append_json(data)


def atomic_json_write(filepath: str, data: Dict[str, Any]) -> bool:
    """Convenience function for writing JSON atomically."""
    writer = AtomicFileWriter(filepath)
    return writer.write_json(data)


__all__ = ["AtomicFileWriter", "atomic_jsonl_append", "atomic_json_write"]
