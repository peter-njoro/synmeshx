"""
Ed25519 signature verification for the Contexa relay server.
Validates incoming device requests by verifying the Ed25519 signature
against the provided public key; rejects any request with an invalid signature.
"""
