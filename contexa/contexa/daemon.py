"""
Daemon entry point and lifecycle manager for Contexa.
Owns startup sequencing (config → logging → DB → stores → sync → API),
graceful shutdown on SIGTERM/SIGINT, and health-state tracking.
"""
