"""Utility functions for symbol filtering."""

from pathlib import Path
from typing import Optional, List, Union


def load_symbols_from_file(
    filepath: Union[str, List[str]], 
    max_symbols: Optional[int] = None
) -> List[str]:
    """Load symbols from one or multiple text files.
    
    Supports multiple formats:
    - One symbol per line
    - Tab-separated: SYMBOL\tDATE\tDATE (extracts first column)
    - Comma-separated: SYMBOL,OTHER,DATA (extracts first column)
    
    Args:
        filepath: Path to symbol file OR list of paths to combine multiple files
        max_symbols: Optional limit on number of symbols to return (applied after combining)
        
    Returns:
        List of unique symbol strings (duplicates removed)
        
    Examples:
        >>> # Single file
        >>> symbols = load_symbols_from_file(".data/nifty500.txt")
        >>> 
        >>> # Multiple files (combine universes)
        >>> symbols = load_symbols_from_file([
        ...     ".data/nifty500.txt",
        ...     ".data/nifty_midcap150.txt",
        ...     ".data/nifty_smallcap250.txt"
        ... ])
    """
    # Handle both single file and list of files
    if isinstance(filepath, str):
        filepaths = [filepath]
    else:
        filepaths = filepath
    
    symbols = []
    
    for fp in filepaths:
        fp = Path(fp).expanduser().resolve()
        
        if not fp.exists():
            raise FileNotFoundError(f"Symbol file not found: {fp}")
        
        with open(fp, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):  # Skip empty lines and comments
                    continue
                
                # Handle tab-separated (first column is symbol)
                if '\t' in line:
                    symbol = line.split('\t')[0].strip()
                # Handle comma-separated
                elif ',' in line:
                    symbol = line.split(',')[0].strip()
                # Single symbol per line
                else:
                    symbol = line.strip()
                
                if symbol:
                    symbols.append(symbol)
    
    # Remove duplicates while preserving order
    seen = set()
    unique_symbols = []
    for symbol in symbols:
        if symbol not in seen:
            seen.add(symbol)
            unique_symbols.append(symbol)
    
    # Apply limit if specified
    if max_symbols is not None and max_symbols > 0:
        unique_symbols = unique_symbols[:max_symbols]
    
    return unique_symbols


def load_nifty500_symbols(max_symbols: Optional[int] = None) -> List[str]:
    """Load NIFTY 500 symbols from default location.
    
    Args:
        max_symbols: Optional limit on number of symbols
        
    Returns:
        List of NIFTY 500 symbols
    """
    # Default path relative to project root
    default_path = Path(__file__).resolve().parents[2] / ".data" / "nifty500.txt"
    return load_symbols_from_file(str(default_path), max_symbols=max_symbols)

