"""Recorder and Experiment classes for tracking quantitative research experiments.

This module wraps MLflow to provide a Qlib-like API for experiment tracking.
"""

from __future__ import annotations

import pickle
from pathlib import Path
from typing import Any, List, Optional

import mlflow
from mlflow.entities import Run
from mlflow.tracking import MlflowClient

DEFAULT_TRACKING_URI = "sqlite:///mlruns.db"


class Experiment:
    """Manages a collection of experiment runs.

    Wraps MLflow experiment functionality to provide a clean interface
    for managing multiple runs within an experiment.

    Example:
        >>> exp = Experiment("my_alpha_research")
        >>> runs = exp.list_runs()
        >>> best_run = exp.search_runs("metrics.sharpe_ratio > 1.5")
    """

    def __init__(self, name: str, tracking_uri: str = None):
        """Initialize an experiment.

        Args:
            name: Name of the experiment
            tracking_uri: MLflow tracking server URI. If None, uses sqlite:///mlruns.db
        """
        self.name = name
        self.tracking_uri = tracking_uri or DEFAULT_TRACKING_URI
        mlflow.set_tracking_uri(self.tracking_uri)

        # Get or create experiment
        self.experiment = mlflow.get_experiment_by_name(name)
        if self.experiment is None:
            self.experiment_id = mlflow.create_experiment(name)
            self.experiment = mlflow.get_experiment(self.experiment_id)
        else:
            self.experiment_id = self.experiment.experiment_id

        self.client = MlflowClient(tracking_uri=self.tracking_uri)

    def list_runs(self, max_results: int = 1000) -> List[Run]:
        """List all runs in this experiment.

        Args:
            max_results: Maximum number of runs to return

        Returns:
            List of MLflow Run objects
        """
        return self.client.search_runs(
            experiment_ids=[self.experiment_id],
            max_results=max_results,
            order_by=["start_time DESC"],
        )

    def get_run(self, run_id: str) -> Run:
        """Get a specific run by ID.

        Args:
            run_id: The run ID to retrieve

        Returns:
            MLflow Run object
        """
        return self.client.get_run(run_id)

    def search_runs(
        self, filter_string: str = "", max_results: int = 1000
    ) -> List[Run]:
        """Search runs by filter criteria.

        Args:
            filter_string: MLflow filter string (e.g., "metrics.IC > 0.05")
            max_results: Maximum number of runs to return

        Returns:
            List of matching Run objects

        Example:
            >>> exp.search_runs("params.model = 'LightGBM' and metrics.sharpe > 1.0")
        """
        return self.client.search_runs(
            experiment_ids=[self.experiment_id],
            filter_string=filter_string,
            max_results=max_results,
            order_by=["start_time DESC"],
        )

    def delete_run(self, run_id: str):
        """Delete a run from the experiment.

        Args:
            run_id: The run ID to delete
        """
        self.client.delete_run(run_id)

    def get_best_run(self, metric: str, ascending: bool = False) -> Optional[Run]:
        """Get the best run based on a metric.

        Args:
            metric: Metric name to optimize (e.g., "sharpe_ratio")
            ascending: If True, lower is better. If False, higher is better.

        Returns:
            The best Run object, or None if no runs exist
        """
        order = "ASC" if ascending else "DESC"
        runs = self.client.search_runs(
            experiment_ids=[self.experiment_id],
            max_results=1,
            order_by=[f"metrics.{metric} {order}"],
        )
        return runs[0] if runs else None


class Recorder:
    """Records experiment parameters, metrics, and artifacts.

    Wraps MLflow run tracking to provide a Qlib-like API for logging
    experiment information during model training and backtesting.

    Example:
        >>> recorder = Recorder("my_alpha_research")
        >>> with recorder.start_run("test_run") as run:
        ...     recorder.log_params(model="LightGBM", features=50)
        ...     recorder.log_metrics(IC=0.05, sharpe_ratio=1.8)
        ...     recorder.save_objects(predictions=pred_df)
    """

    def __init__(self, experiment_name: str, tracking_uri: str = None):
        """Initialize a recorder.

        Args:
            experiment_name: Name of the experiment this recorder belongs to
            tracking_uri: MLflow tracking server URI. If None, uses sqlite:///mlruns.db
        """
        self.experiment_name = experiment_name
        self.tracking_uri = tracking_uri or DEFAULT_TRACKING_URI
        mlflow.set_tracking_uri(self.tracking_uri)

        # Get or create experiment
        self.experiment = mlflow.get_experiment_by_name(experiment_name)
        if self.experiment is None:
            self.experiment_id = mlflow.create_experiment(experiment_name)
        else:
            self.experiment_id = self.experiment.experiment_id

        self.client = MlflowClient(tracking_uri=self.tracking_uri)
        self._active_run = None

    @property
    def active_run(self):
        """Get the currently active run."""
        return self._active_run

    def start_run(self, run_name: str = None, nested: bool = False):
        """Start a new run or resume an existing one.

        Args:
            run_name: Optional name for the run
            nested: If True, start a nested run

        Returns:
            ActiveRun context manager

        Example:
            >>> with recorder.start_run("my_experiment"):
            ...     recorder.log_params(alpha=0.1)
        """
        run = mlflow.start_run(
            experiment_id=self.experiment_id, run_name=run_name, nested=nested
        )
        self._active_run = run
        
        # Return a wrapped context manager that clears _active_run on exit
        class _ActiveRunWrapper:
            def __init__(self, run, recorder):
                self.run = run
                self.recorder = recorder
            
            def __enter__(self):
                return self.run.__enter__()
            
            def __exit__(self, exc_type, exc_val, exc_tb):
                result = self.run.__exit__(exc_type, exc_val, exc_tb)
                self.recorder._active_run = None
                return result
        
        return _ActiveRunWrapper(run, self)

    def end_run(self):
        """End the currently active run."""
        if self._active_run is not None:
            mlflow.end_run()
            self._active_run = None

    def log_params(self, **kwargs):
        """Log parameters for the current run.

        Args:
            **kwargs: Key-value pairs of parameters to log

        Example:
            >>> recorder.log_params(model="LightGBM", learning_rate=0.1, max_depth=5)
        """
        if self._active_run is None:
            raise RuntimeError("No active run. Call start_run() first.")
        mlflow.log_params(kwargs)

    def log_metrics(self, step: int = None, **kwargs):
        """Log metrics for the current run.

        Args:
            step: Optional step number for time-series metrics
            **kwargs: Key-value pairs of metrics to log

        Example:
            >>> recorder.log_metrics(IC=0.05, rank_IC=0.08, sharpe_ratio=1.8)
            >>> recorder.log_metrics(step=10, portfolio_value=1050000)
        """
        if self._active_run is None:
            raise RuntimeError("No active run. Call start_run() first.")

        for key, value in kwargs.items():
            mlflow.log_metric(key, value, step=step)

    def log_artifact(self, local_path: str, artifact_path: str = None):
        """Log a file or directory as an artifact.

        Args:
            local_path: Path to the local file or directory
            artifact_path: Optional subdirectory in artifact store

        Example:
            >>> recorder.log_artifact("predictions.csv")
            >>> recorder.log_artifact("model.pkl", artifact_path="models")
        """
        if self._active_run is None:
            raise RuntimeError("No active run. Call start_run() first.")
        mlflow.log_artifact(local_path, artifact_path=artifact_path)

    def save_objects(self, artifact_path: str = None, **kwargs):
        """Save Python objects as pickled artifacts.

        Args:
            artifact_path: Optional subdirectory in artifact store
            **kwargs: Key-value pairs where keys are names and values are objects

        Example:
            >>> recorder.save_objects(
            ...     predictions=pred_df,
            ...     feature_importance=fi_dict,
            ...     model=trained_model
            ... )
        """
        if self._active_run is None:
            raise RuntimeError("No active run. Call start_run() first.")

        # Create temp directory for artifacts
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            for name, obj in kwargs.items():
                obj_path = tmpdir_path / f"{name}.pkl"
                with open(obj_path, "wb") as f:
                    pickle.dump(obj, f)
                mlflow.log_artifact(str(obj_path), artifact_path=artifact_path)

    def load_object(self, name: str, run_id: str = None) -> Any:
        """Load a saved object from artifacts.

        Args:
            name: Name of the object (without .pkl extension)
            run_id: Optional run ID. If None, uses current active run.

        Returns:
            The unpickled object

        Example:
            >>> predictions = recorder.load_object("predictions")
        """
        if run_id is None:
            if self._active_run is None:
                raise RuntimeError("No active run and no run_id provided.")
            run_id = self._active_run.info.run_id

        # Download artifact
        artifact_path = self.client.download_artifacts(run_id, f"{name}.pkl")
        with open(artifact_path, "rb") as f:
            return pickle.load(f)

    def set_tags(self, **kwargs):
        """Set tags for the current run.

        Args:
            **kwargs: Key-value pairs of tags to set

        Example:
            >>> recorder.set_tags(strategy="momentum", dataset="US_stocks")
        """
        if self._active_run is None:
            raise RuntimeError("No active run. Call start_run() first.")
        mlflow.set_tags(kwargs)

    def log_artifact_dataframe(self, df, name: str, artifact_path: str = None):
        """Log a pandas DataFrame as a parquet artifact.

        Args:
            df: Pandas DataFrame to save
            name: Name for the artifact (without extension)
            artifact_path: Optional subdirectory in artifact store

        Example:
            >>> recorder.log_artifact_dataframe(predictions_df, "predictions")
        """
        if self._active_run is None:
            raise RuntimeError("No active run. Call start_run() first.")

        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / f"{name}.parquet"
            df.to_parquet(file_path)
            mlflow.log_artifact(str(file_path), artifact_path=artifact_path)

    def get_experiment(self) -> Experiment:
        """Get the Experiment object for this recorder.

        Returns:
            Experiment object
        """
        return Experiment(self.experiment_name, self.tracking_uri)

