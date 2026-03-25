"""
SQLAlchemy engine and session factory for Contexa.
Targets ~/.local/share/contexa/contexa.db and exposes init_db() which
runs Alembic migrations to bring the schema up to date.
"""
