"""Database models for alphacopilot server."""

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any

from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Text, Enum as SQLEnum
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import relationship

from .database import Base


class RunStatus(str, Enum):
    """Status of a run."""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class Run(Base):
    """Run model - represents a single workflow execution."""
    __tablename__ = "runs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    hypothesis = Column(Text, nullable=False)
    status = Column(SQLEnum(RunStatus), default=RunStatus.PENDING, nullable=False)
    config = Column(JSON, nullable=False)  # All parameters as JSON
    num_iterations = Column(Integer, nullable=False)
    current_iteration = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    error_message = Column(Text, nullable=True)

    # Relationships
    iterations = relationship("Iteration", back_populates="run", cascade="all, delete-orphan")
    result = relationship("Result", back_populates="run", uselist=False, cascade="all, delete-orphan")
    logs = relationship("Log", back_populates="run", cascade="all, delete-orphan", order_by="Log.timestamp")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "hypothesis": self.hypothesis,
            "status": self.status.value,
            "config": self.config,
            "num_iterations": self.num_iterations,
            "current_iteration": self.current_iteration,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "error_message": self.error_message,
        }


class Iteration(Base):
    """Iteration model - represents a single iteration within a run."""
    __tablename__ = "iterations"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id = Column(String, ForeignKey("runs.id"), nullable=False)
    iteration_num = Column(Integer, nullable=False)
    factors = Column(JSON, nullable=True)  # List of factor expressions
    metrics = Column(JSON, nullable=True)  # Iteration metrics
    completed_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    run = relationship("Run", back_populates="iterations")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "run_id": self.run_id,
            "iteration_num": self.iteration_num,
            "factors": self.factors,
            "metrics": self.metrics,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class Result(Base):
    """Result model - final results for a completed run."""
    __tablename__ = "results"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id = Column(String, ForeignKey("runs.id"), nullable=False, unique=True)
    final_metrics = Column(JSON, nullable=True)  # Final metrics
    all_factors = Column(JSON, nullable=True)  # All factors from all iterations
    best_factors = Column(JSON, nullable=True)  # SOTA factors if applicable
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    run = relationship("Run", back_populates="result")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "run_id": self.run_id,
            "final_metrics": self.final_metrics,
            "all_factors": self.all_factors,
            "best_factors": self.best_factors,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Log(Base):
    """Log model - stores log entries for a run."""
    __tablename__ = "logs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id = Column(String, ForeignKey("runs.id"), nullable=False, index=True)
    level = Column(String, nullable=False)  # INFO, DEBUG, WARNING, ERROR
    message = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Relationships
    run = relationship("Run", back_populates="logs")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "run_id": self.run_id,
            "level": self.level,
            "message": self.message,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }

