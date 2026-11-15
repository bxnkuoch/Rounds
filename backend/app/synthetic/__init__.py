"""Seeded synthetic staff and jobs (clearly labeled) on a real building's places."""

from app.synthetic.generator import (
    ROLE_FOR_KIND, SERVICE_MINUTES, Scenario, SyntheticJob, SyntheticStaff, generate_scenario,
)

__all__ = ["ROLE_FOR_KIND", "SERVICE_MINUTES", "Scenario", "SyntheticJob", "SyntheticStaff", "generate_scenario"]
