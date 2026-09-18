"""Strategy DSL: JSON rules over stored indicators, validated then INTERPRETED.

Strategies are DATA. Nothing in this package (or anywhere in the codebase)
compiles or executes code from a spec -- that is a project ground rule, and
it is what makes it safe for an AI to propose strategies at all: the worst a
malicious or confused spec can do is fail validation.
"""
