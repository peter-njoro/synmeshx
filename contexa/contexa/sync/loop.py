"""
Background sync loop for the Contexa daemon.

The daemon holds one persistent relay connection for its whole lifetime: the
transport's receive loop is always listening so peers can sync *to* this device
at any time, while this loop periodically initiates sync *from* this device to
each trusted peer. A manual POST /sync/trigger fires a cycle immediately by
setting the trigger event this loop waits on.

Wired up in the FastAPI lifespan (see api/app.py) so it shares the server's
event loop and is cancelled cleanly on shutdown.
"""

from __future__ import annotations

import asyncio
import logging

from contexa.store.models import DeviceRecord
from contexa.sync.relay_client import RelayConnectionError
from contexa.sync.transport import RelaySyncTransport

logger = logging.getLogger(__name__)

# How long to back off before reconnecting after a relay failure.
_RECONNECT_MAX_DELAY = 30.0


async def run_sync_loop(app) -> None:
    """Run the daemon's sync loop until cancelled.

    Reads everything it needs from app.state (populated by the daemon):
      sync_engine, trust_store, config, identity_id, and the sync_trigger event.
    Returns early (does nothing) when sync is not usable — local-only mode or
    no identity_id to form a trust group with.
    """
    state = app.state
    engine = state.sync_engine
    cfg = state.config
    trust_store = state.trust_store
    identity = trust_store.identity
    identity_id = getattr(state, "identity_id", None)
    trigger: asyncio.Event = state.sync_trigger
    interval = cfg.sync.interval_seconds

    if not engine.is_relay_mode():
        logger.info("Sync loop disabled: local-only mode (no relay)")
        return
    if not identity_id:
        logger.warning(
            "Sync loop disabled: device has no identity_id — run 'contexa auth login'"
        )
        return

    relay_url = engine.get_relay_url()
    logger.info("Sync loop starting (relay=%s, interval=%ss)", relay_url, interval)

    while True:
        try:
            async with RelaySyncTransport(
                engine,
                relay_url,
                identity,
                trust_group_id=identity_id,
                identity_id=identity_id,
            ) as transport:
                engine.mark_relay_available()
                logger.info("Connected to relay %s", relay_url)
                while True:
                    await _run_cycle(transport, trust_store, state)
                    trigger.clear()
                    try:
                        await asyncio.wait_for(trigger.wait(), timeout=interval)
                    except asyncio.TimeoutError:
                        pass  # interval elapsed — run the next cycle
        except asyncio.CancelledError:
            logger.info("Sync loop cancelled")
            raise
        except (RelayConnectionError, OSError) as e:
            engine.mark_relay_unavailable()
            logger.warning("Relay connection lost: %s — reconnecting", e)
        except Exception as e:  # noqa: BLE001 — never let the loop die silently
            logger.error("Sync loop error: %s — reconnecting", e)

        try:
            await asyncio.sleep(min(interval, _RECONNECT_MAX_DELAY))
        except asyncio.CancelledError:
            raise


async def _run_cycle(transport: RelaySyncTransport, trust_store, state) -> None:
    """Initiate a sync with every trusted peer once."""
    peers = [entry.device_id for entry in trust_store.list_trusted()]
    if not peers:
        logger.debug("Sync cycle: no trusted peers")
        return

    for peer_id in peers:
        try:
            result = await transport.initiate_sync(peer_id)
        except asyncio.TimeoutError:
            logger.debug("Peer %s did not respond (offline?)", peer_id)
            continue
        except Exception as e:  # noqa: BLE001
            logger.warning("Sync with peer %s failed: %s", peer_id, e)
            state.sync_failures += 1
            continue

        state.syncs_completed += 1
        logger.info(
            "Synced with %s: %d accepted, %d conflicts, %d failed",
            peer_id, len(result.accepted), len(result.conflicts), len(result.failed),
        )
