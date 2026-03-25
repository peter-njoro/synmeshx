"""
Sync_Engine: orchestrates push/pull replication between trusted devices.
Manages peer connections, executes the HELLO→KNOWN_VERSIONS→PUSH→ACK
protocol, detects conflicts, writes sync_log entries, and handles
offline queuing with exponential-backoff retry.
"""
