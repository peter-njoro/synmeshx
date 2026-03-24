# Contexa Relay — Definition

## Overview
The Contexa Relay is a lightweight network component responsible for enabling secure communication between Contexa-enabled devices over the internet.

It is not part of the core context engine and does not store or interpret context. Its sole purpose is to facilitate message exchange between authenticated devices that cannot communicate directly.

---

## Core Role

> The relay acts as a secure message router between trusted devices.

It exists to:
- Bridge network boundaries (e.g., NAT, firewalls)
- Enable device-to-device synchronization over the internet
- Provide connectivity when direct peer-to-peer communication is not possible

---

## Responsibilities

The relay is intentionally minimal. It should:

- Accept incoming connections from devices
- Authenticate devices (e.g., via signed requests or tokens)
- Route encrypted messages between devices
- Maintain temporary connection/session state (if needed)

---

## Non-Responsibilities

The relay must NOT:

- Store long-term context data
- Interpret or process context content
- Act as a source of truth
- Implement business logic
- Require a frontend or user interface

---

## Security Model

- All payloads are end-to-end encrypted between devices
- The relay cannot read or modify context data
- Devices authenticate themselves before communication
- Only trusted devices can exchange messages

---

## Deployment Model

The relay is designed to be:

### 1. Self-Hostable
- Users can deploy their own relay (e.g., via Docker)
- Full control over infrastructure and data flow

### 2. Optionally Hosted
- A default hosted relay may be provided for convenience
- No dependency on a central service is required

---

## Multi-Device Isolation

- Devices are grouped by a shared identity (user scope)
- The relay ensures that:
  - Devices can only communicate within their trusted group
  - Cross-user/device communication is not allowed

---

## Operational Characteristics

- Stateless or minimally stateful
- Horizontally scalable
- Replaceable without breaking the system
- Network-facing component (publicly reachable)

---

## Mental Model

The Contexa Relay can be thought of as:

- A “dumb pipe with authentication”
- A secure message switch
- A transport layer for device communication

---

## Summary

> The Contexa Relay is a minimal, secure routing layer that enables authenticated devices to exchange encrypted messages over the internet without acting as a central authority or data store.

---