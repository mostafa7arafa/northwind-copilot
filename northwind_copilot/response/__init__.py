"""Response layer: turn agent output into the user-facing answer.

Re-runs the final SQL for a clean result table, infers a chart when the model
did not draw one (:mod:`~northwind_copilot.response.charting`), and translates
the agent's message stream into structured pipeline events
(:mod:`~northwind_copilot.response.streaming`).
"""
