"""
Ephemeral in-memory session registry for the Contexa relay server.
Tracks active WebSocket connections by device_id and trust-group membership;
all state is lost on restart — no persistence.
"""
