"""AI features: the evening review and the weekly strategy lab.

Only this package talks to an LLM (an import-linter contract enforces it), and nothing in the API
imports it: the dashboard reads stored outputs, it never triggers a call.
"""
