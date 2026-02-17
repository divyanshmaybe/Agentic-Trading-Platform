"""LSTM model implementation for quantitative forecasting."""

from typing import Optional, Tuple

import pandas as pd
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

from quant_stream.models.base import ForecastModel


class LSTMNet(nn.Module):
    """PyTorch LSTM network for time series forecasting.

    This network uses LSTM layers to capture temporal dependencies
    in financial time series data.
    """

    def __init__(
        self,
        input_size: int,
        hidden_size: int = 64,
        num_layers: int = 2,
        dropout: float = 0.2,
        bidirectional: bool = False,
    ):
        """Initialize LSTM network.

        Args:
            input_size: Number of input features
            hidden_size: Number of hidden units in LSTM
            num_layers: Number of LSTM layers
            dropout: Dropout rate between LSTM layers
            bidirectional: Whether to use bidirectional LSTM
        """
        super(LSTMNet, self).__init__()

        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.bidirectional = bidirectional

        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            dropout=dropout if num_layers > 1 else 0,
            batch_first=True,
            bidirectional=bidirectional,
        )

        # Output layer
        lstm_output_size = hidden_size * 2 if bidirectional else hidden_size
        self.fc = nn.Linear(lstm_output_size, 1)

    def forward(self, x):
        """Forward pass.

        Args:
            x: Input tensor of shape (batch_size, seq_len, input_size)

        Returns:
            Output tensor of shape (batch_size, 1)
        """
        # LSTM forward pass
        lstm_out, _ = self.lstm(x)

        # Take the output from the last time step
        last_output = lstm_out[:, -1, :]

        # Pass through fully connected layer
        out = self.fc(last_output)

        return out


class LSTMModel(ForecastModel):
    """LSTM model for financial forecasting.

    This model uses Long Short-Term Memory (LSTM) networks to capture
    temporal dependencies in financial time series. It's particularly
    effective for modeling sequential patterns and dependencies.

    Example:
        >>> model = LSTMModel(
        ...     hidden_size=64,
        ...     num_layers=2,
        ...     sequence_length=20,
        ...     epochs=50
        ... )
        >>> model.fit(X_train, y_train)
        >>> predictions = model.predict(X_test)
    """

    def __init__(
        self,
        hidden_size: int = 64,
        num_layers: int = 2,
        dropout: float = 0.2,
        bidirectional: bool = False,
        sequence_length: int = 20,
        batch_size: int = 64,
        epochs: int = 50,
        learning_rate: float = 0.001,
        weight_decay: float = 1e-5,
        early_stopping_patience: int = 10,
        device: str = None,
        verbose: bool = True,
        **kwargs,
    ):
        """Initialize LSTM model.

        Args:
            hidden_size: Number of hidden units in LSTM
            num_layers: Number of LSTM layers
            dropout: Dropout rate between LSTM layers
            bidirectional: Whether to use bidirectional LSTM
            sequence_length: Length of input sequences (lookback window)
            batch_size: Batch size for training
            epochs: Maximum number of training epochs
            learning_rate: Learning rate for optimizer
            weight_decay: L2 regularization parameter
            early_stopping_patience: Patience for early stopping (epochs)
            device: Device to use ('cuda', 'mps', 'cpu', or None for auto)
            verbose: Whether to print training progress
            **kwargs: Additional parameters passed to base class
        """
        super().__init__(**kwargs)

        # Model architecture parameters
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.dropout = dropout
        self.bidirectional = bidirectional
        self.sequence_length = sequence_length

        # Training parameters
        self.batch_size = batch_size
        self.epochs = epochs
        self.learning_rate = learning_rate
        self.weight_decay = weight_decay
        self.early_stopping_patience = early_stopping_patience
        self.verbose = verbose

        # Device setup
        if device is None:
            # Auto-select device: prefer CUDA, then MPS, then CPU
            if torch.cuda.is_available():
                self.device = torch.device("cuda")
            elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                self.device = torch.device("mps")
            else:
                self.device = torch.device("cpu")
        else:
            self.device = torch.device(device)

        # Model will be initialized in fit()
        self.model = None
        self.scaler_X = None
        self.scaler_y = None

    def _create_sequences(
        self, X: pd.DataFrame, y: pd.Series = None
    ) -> Tuple[np.ndarray, Optional[np.ndarray]]:
        """Create sequences from time series data.

        Args:
            X: Feature dataframe
            y: Target series (optional)

        Returns:
            Tuple of (X_sequences, y_sequences) or (X_sequences, None)
        """
        X_values = X.values
        n_samples = len(X_values)

        if n_samples < self.sequence_length:
            raise ValueError(
                f"Data length ({n_samples}) is less than sequence_length "
                f"({self.sequence_length}). Need at least {self.sequence_length} samples."
            )

        X_sequences = []
        y_sequences = [] if y is not None else None

        for i in range(self.sequence_length, n_samples + 1):
            X_sequences.append(X_values[i - self.sequence_length : i])
            if y is not None:
                y_sequences.append(y.iloc[i - 1])

        X_sequences = np.array(X_sequences)

        if y is not None:
            y_sequences = np.array(y_sequences)
            return X_sequences, y_sequences

        return X_sequences, None

    def _normalize_data(
        self, X: np.ndarray, y: np.ndarray = None, fit_scalers: bool = False
    ) -> Tuple[np.ndarray, Optional[np.ndarray]]:
        """Normalize data using standardization.

        Args:
            X: Feature array
            y: Target array (optional)
            fit_scalers: Whether to fit scalers on this data

        Returns:
            Tuple of (normalized_X, normalized_y)
        """
        # Reshape X for scaling: (n_samples, seq_len, features) -> (n_samples * seq_len, features)
        original_shape = X.shape
        X_reshaped = X.reshape(-1, X.shape[-1])

        if fit_scalers:
            # Fit scalers
            X_mean = X_reshaped.mean(axis=0)
            X_std = X_reshaped.std(axis=0) + 1e-8  # Avoid division by zero
            self.scaler_X = (X_mean, X_std)

            if y is not None:
                y_mean = y.mean()
                y_std = y.std() + 1e-8
                self.scaler_y = (y_mean, y_std)

        # Normalize X
        X_normalized = (X_reshaped - self.scaler_X[0]) / self.scaler_X[1]
        X_normalized = X_normalized.reshape(original_shape)

        # Normalize y
        if y is not None and self.scaler_y is not None:
            y_normalized = (y - self.scaler_y[0]) / self.scaler_y[1]
            return X_normalized, y_normalized

        return X_normalized, y

    def _denormalize_predictions(self, y_normalized: np.ndarray) -> np.ndarray:
        """Denormalize predictions back to original scale.

        Args:
            y_normalized: Normalized predictions

        Returns:
            Denormalized predictions
        """
        if self.scaler_y is None:
            return y_normalized

        return y_normalized * self.scaler_y[1] + self.scaler_y[0]

    def fit(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        eval_set: tuple = None,
        **kwargs,
    ) -> "LSTMModel":
        """Fit the LSTM model.

        Args:
            X: Training features
            y: Training targets
            eval_set: Optional validation set as (X_val, y_val) tuple
            **kwargs: Additional parameters (unused, for compatibility)

        Returns:
            Self (for method chaining)

        Example:
            >>> model.fit(X_train, y_train, eval_set=(X_val, y_val))
        """
        # Store feature names
        self.feature_names = list(X.columns)
        input_size = len(self.feature_names)

        # Create sequences
        X_seq, y_seq = self._create_sequences(X, y)

        # Normalize data
        X_seq, y_seq = self._normalize_data(X_seq, y_seq, fit_scalers=True)

        # Convert to PyTorch tensors
        X_tensor = torch.FloatTensor(X_seq).to(self.device)
        y_tensor = torch.FloatTensor(y_seq).reshape(-1, 1).to(self.device)

        # Create DataLoader
        train_dataset = TensorDataset(X_tensor, y_tensor)
        train_loader = DataLoader(
            train_dataset, batch_size=self.batch_size, shuffle=True
        )

        # Handle validation set
        val_loader = None
        if eval_set is not None:
            X_val, y_val = eval_set
            X_val_seq, y_val_seq = self._create_sequences(X_val, y_val)
            X_val_seq, y_val_seq = self._normalize_data(X_val_seq, y_val_seq, fit_scalers=False)

            X_val_tensor = torch.FloatTensor(X_val_seq).to(self.device)
            y_val_tensor = torch.FloatTensor(y_val_seq).reshape(-1, 1).to(self.device)

            val_dataset = TensorDataset(X_val_tensor, y_val_tensor)
            val_loader = DataLoader(
                val_dataset, batch_size=self.batch_size, shuffle=False
            )

        # Initialize model
        self.model = LSTMNet(
            input_size=input_size,
            hidden_size=self.hidden_size,
            num_layers=self.num_layers,
            dropout=self.dropout,
            bidirectional=self.bidirectional,
        ).to(self.device)

        # Loss and optimizer
        criterion = nn.MSELoss()
        optimizer = torch.optim.Adam(
            self.model.parameters(),
            lr=self.learning_rate,
            weight_decay=self.weight_decay,
        )

        # Training loop
        best_val_loss = float("inf")
        patience_counter = 0

        for epoch in range(self.epochs):
            # Training phase
            self.model.train()
            train_loss = 0.0

            for batch_X, batch_y in train_loader:
                optimizer.zero_grad()

                # Forward pass
                outputs = self.model(batch_X)
                loss = criterion(outputs, batch_y)

                # Backward pass
                loss.backward()
                optimizer.step()

                train_loss += loss.item()

            train_loss /= len(train_loader)

            # Validation phase
            if val_loader is not None:
                self.model.eval()
                val_loss = 0.0

                with torch.no_grad():
                    for batch_X, batch_y in val_loader:
                        outputs = self.model(batch_X)
                        loss = criterion(outputs, batch_y)
                        val_loss += loss.item()

                val_loss /= len(val_loader)

                # Early stopping
                if val_loss < best_val_loss:
                    best_val_loss = val_loss
                    patience_counter = 0
                    # Save best model state
                    self.best_model_state = self.model.state_dict().copy()
                else:
                    patience_counter += 1

                if self.verbose and (epoch + 1) % 10 == 0:
                    print(
                        f"Epoch [{epoch+1}/{self.epochs}] "
                        f"Train Loss: {train_loss:.4f} "
                        f"Val Loss: {val_loss:.4f}"
                    )

                # Early stopping check
                if patience_counter >= self.early_stopping_patience:
                    if self.verbose:
                        print(f"Early stopping at epoch {epoch+1}")
                    # Restore best model
                    self.model.load_state_dict(self.best_model_state)
                    break
            else:
                if self.verbose and (epoch + 1) % 10 == 0:
                    print(f"Epoch [{epoch+1}/{self.epochs}] Train Loss: {train_loss:.4f}")

        self.is_fitted = True
        return self

    def predict(self, X: pd.DataFrame) -> pd.Series:
        """Generate predictions.

        Args:
            X: Features to predict on

        Returns:
            Predictions as pandas Series

        Example:
            >>> predictions = model.predict(X_test)
        """
        if not self.is_fitted:
            raise RuntimeError(
                "Model must be fitted before prediction. Call fit() first."
            )

        # Create sequences
        X_seq, _ = self._create_sequences(X)

        # Normalize data
        X_seq, _ = self._normalize_data(X_seq, fit_scalers=False)

        # Convert to PyTorch tensor
        X_tensor = torch.FloatTensor(X_seq).to(self.device)

        # Make predictions
        self.model.eval()
        with torch.no_grad():
            predictions = self.model(X_tensor).cpu().numpy().flatten()

        # Denormalize predictions
        predictions = self._denormalize_predictions(predictions)

        # Create index for predictions (they correspond to the last item in each sequence)
        prediction_index = X.index[self.sequence_length - 1 :]

        return pd.Series(predictions, index=prediction_index)

    def get_feature_importance(self) -> pd.Series:
        """Get feature importance (not applicable for LSTM).

        Note: Feature importance is not well-defined for LSTM models.
        This method returns uniform importance for compatibility.

        Returns:
            Series with uniform feature importances
        """
        if not self.is_fitted:
            raise RuntimeError(
                "Model must be fitted first. Call fit() before getting importance."
            )

        # LSTM doesn't have feature importance like tree models
        # Return uniform importance
        importance = pd.Series(
            1.0 / len(self.feature_names),
            index=self.feature_names,
        )

        return importance

    def save(self, path: str):
        """Save the model to disk.

        Args:
            path: File path to save the model

        Example:
            >>> model.save("lstm_model.pt")
        """
        if not self.is_fitted:
            raise RuntimeError("Cannot save unfitted model. Call fit() first.")

        # Ensure path has .pt extension
        if not path.endswith(".pt"):
            path = path + ".pt"

        # Save model state and parameters
        torch.save(
            {
                "model_state_dict": self.model.state_dict(),
                "hidden_size": self.hidden_size,
                "num_layers": self.num_layers,
                "dropout": self.dropout,
                "bidirectional": self.bidirectional,
                "sequence_length": self.sequence_length,
                "feature_names": self.feature_names,
                "scaler_X": self.scaler_X,
                "scaler_y": self.scaler_y,
            },
            path,
        )

    @classmethod
    def load(cls, path: str) -> "LSTMModel":
        """Load a saved model from disk.

        Args:
            path: File path to load the model from

        Returns:
            Loaded LSTMModel instance

        Example:
            >>> model = LSTMModel.load("lstm_model.pt")
        """
        # Ensure path has .pt extension
        if not path.endswith(".pt"):
            path = path + ".pt"

        # Load checkpoint
        checkpoint = torch.load(path, map_location="cpu")

        # Create new instance with saved parameters
        model_instance = cls(
            hidden_size=checkpoint["hidden_size"],
            num_layers=checkpoint["num_layers"],
            dropout=checkpoint["dropout"],
            bidirectional=checkpoint["bidirectional"],
            sequence_length=checkpoint["sequence_length"],
        )

        # Restore model architecture
        input_size = len(checkpoint["feature_names"])
        model_instance.model = LSTMNet(
            input_size=input_size,
            hidden_size=checkpoint["hidden_size"],
            num_layers=checkpoint["num_layers"],
            dropout=checkpoint["dropout"],
            bidirectional=checkpoint["bidirectional"],
        ).to(model_instance.device)

        # Load model weights
        model_instance.model.load_state_dict(checkpoint["model_state_dict"])
        model_instance.model.eval()

        # Restore other attributes
        model_instance.feature_names = checkpoint["feature_names"]
        model_instance.scaler_X = checkpoint["scaler_X"]
        model_instance.scaler_y = checkpoint["scaler_y"]
        model_instance.is_fitted = True

        return model_instance
