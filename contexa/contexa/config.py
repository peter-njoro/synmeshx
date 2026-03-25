"""
Configuration loader for Contexa.
Reads ~/.config/contexa/config.toml via tomllib, maps values onto the
ContexaConfig dataclass, and applies documented defaults when the file is absent.
"""
