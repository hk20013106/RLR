"""RLR software-maintenance boundary.

The package is intentionally separate from ``research_loop`` so maintenance
coordination cannot become a second owner of scientific state or DAG authority.
"""

from .contracts import (
    MAINTENANCE_EVENT_SCHEMA,
    MaintenanceContractError,
    build_maintenance_event,
    canonical_json,
    validate_maintenance_event,
)

__all__ = [
    "MAINTENANCE_EVENT_SCHEMA",
    "MaintenanceContractError",
    "build_maintenance_event",
    "canonical_json",
    "validate_maintenance_event",
]
