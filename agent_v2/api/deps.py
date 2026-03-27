"""
Dependency injection for API routes.

Provides access to shared components initialized in the app lifespan.
"""

from __future__ import annotations

from src.agent.coordinator import CoordinatorAgent
from src.dal.database import DatabaseAbstractionLayer

# These are populated during app lifespan startup (see main.py)
_dal: DatabaseAbstractionLayer | None = None
_coordinator: CoordinatorAgent | None = None


def get_dal() -> DatabaseAbstractionLayer | None:
    return _dal


def get_coordinator() -> CoordinatorAgent | None:
    return _coordinator


def set_dal(dal: DatabaseAbstractionLayer | None):
    global _dal
    _dal = dal


def set_coordinator(coordinator: CoordinatorAgent | None):
    global _coordinator
    _coordinator = coordinator
