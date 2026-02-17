"""Utility functions for recorder module."""

from pathlib import Path
from typing import Optional

import pandas as pd
import pathway as pw

from quant_stream.recorder.recorder import DEFAULT_TRACKING_URI


def pathway_table_to_dataframe(table: pw.Table) -> pd.DataFrame:
    """Convert a Pathway table to a pandas DataFrame.

    Args:
        table: Pathway table to convert

    Returns:
        Pandas DataFrame

    Note:
        This function materializes the entire table into memory.
        Use with caution for large tables.
    """
    # Use Pathway's debug utility to convert table to pandas
    return pw.debug.table_to_pandas(table)


def save_pathway_table_artifact(
    table: pw.Table, name: str, output_dir: Path, format: str = "parquet"
) -> Path:
    """Save a Pathway table as an artifact file.

    Args:
        table: Pathway table to save
        name: Name for the artifact file
        output_dir: Directory to save the file
        format: File format ('parquet' or 'csv')

    Returns:
        Path to the saved file
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Convert table to pandas first
    df = pathway_table_to_dataframe(table)
    
    if format == "parquet":
        file_path = output_dir / f"{name}.parquet"
        df.to_parquet(file_path, index=False)
    elif format == "csv":
        file_path = output_dir / f"{name}.csv"
        df.to_csv(file_path, index=False)
    else:
        raise ValueError(f"Unsupported format: {format}")

    return file_path


def load_mlflow_run_artifacts(
    run_id: str, artifact_names: list[str], tracking_uri: str = None
) -> dict:
    """Load multiple artifacts from an MLflow run.

    Args:
        run_id: MLflow run ID
        artifact_names: List of artifact names to load
        tracking_uri: MLflow tracking URI

    Returns:
        Dictionary mapping artifact names to loaded objects
    """
    import mlflow
    from mlflow.tracking import MlflowClient

    tracking_uri = tracking_uri or DEFAULT_TRACKING_URI
    client = MlflowClient(tracking_uri=tracking_uri)

    artifacts = {}
    for name in artifact_names:
        try:
            # Try to load as pickle
            import pickle

            artifact_path = client.download_artifacts(run_id, f"{name}.pkl")
            with open(artifact_path, "rb") as f:
                artifacts[name] = pickle.load(f)
        except Exception:
            # Try to load as parquet
            try:
                artifact_path = client.download_artifacts(run_id, f"{name}.parquet")
                artifacts[name] = pd.read_parquet(artifact_path)
            except Exception:
                # Try to load as CSV
                try:
                    artifact_path = client.download_artifacts(run_id, f"{name}.csv")
                    artifacts[name] = pd.read_csv(artifact_path)
                except Exception as e:
                    print(f"Failed to load artifact {name}: {e}")

    return artifacts

