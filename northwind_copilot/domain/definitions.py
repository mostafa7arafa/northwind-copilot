"""Core business definitions for Northwind retail analytics.

These constants are the single source of truth for the formulas the analyst
agent must apply. They are interpolated into the system prompt so the prose and
the rules can never drift apart.
"""

from __future__ import annotations

#: SQL expression for line-item revenue, per the KPI documentation.
REVENUE_SQL: str = "UnitPrice * Quantity * (1 - Discount)"

#: Gross margin as a fraction of revenue. Cost of goods is assumed to be 70% of
#: UnitPrice when not otherwise available, so margin is 30% of revenue.
MARGIN_RATE: float = 0.30
