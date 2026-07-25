"""SQLite cache store and resolution ladder (phase 2 — not yet implemented).

Per DESIGN.md, commands never touch SQL directly: they ask this module for a
result set, and it either serves from the DB or delegates to walk.py. This
module is currently a stub; v0 commands call walk.py directly.
"""
