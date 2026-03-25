"""
FastAPI WebSocket application entry point for the Contexa relay server.
Handles device connections, runs the Ed25519 auth challenge, registers
sessions, routes messages, and exposes a GET /health HTTP endpoint.
"""
