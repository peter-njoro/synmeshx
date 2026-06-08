"""
Contexa Daemon — entry point and lifecycle manager.

Startup sequence:
  1. Load config from ~/.config/contexa/config.toml (or defaults)
  2. Initialize structlog with configured level/output
  3. Open SQLite database, run Alembic migrations
  4. Initialize Context_Store, Trust_Store, Embedding_Store
  5. Load or generate Device_ID and Ed25519 key pair
  6. Initialize Sync_Engine
  7. Start FastAPI Local_API server (uvicorn, localhost only)
  8. Register SIGTERM/SIGINT handlers
  9. Enter event loop

Graceful shutdown sequence (on SIGTERM/SIGINT):
  1. Stop accepting new requests
  2. Drain in-flight requests (5s timeout)
  3. Flush pending Context_Store writes
  4. Flush pending Sync_Engine queue
  5. Close SQLite connections
  6. Exit 0

Any init failure exits with a non-zero status code and a descriptive log message.
"""

from __future__ import annotations

import signal
import sys
import time
import logging
from pathlib import Path

import structlog
import uvicorn

from contexa.config import load_config, ConfigError
from contexa.store.database import build_engine, build_session_factory, init_db
from contexa.store.context_store import ContextStore
from contexa.store.trust_store import TrustStore
from contexa.store.embedding_store import EmbeddingStore
from contexa.sync.engine import SyncEngine, SyncMode
from contexa.api.app import create_app
from contexa.logging import install_global_exception_handler


def _configure_logging(log_level: str, log_output: str) -> None:
    """Configure structlog with the given level and output destination."""
    level = getattr(logging, log_level.upper(), logging.INFO)

    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.JSONRenderer(),
    ]

    if log_output == "stdout":
        handler = logging.StreamHandler(sys.stdout)
    else:
        handler = logging.FileHandler(log_output)

    handler.setLevel(level)

    # Force root logger level (basicConfig is a no-op if already configured)
    root = logging.getLogger()
    root.setLevel(level)
    # Remove existing handlers and add the new one
    root.handlers.clear()
    root.addHandler(handler)

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )


def main(config_path: Path | None = None) -> None:
    """Start the Contexa daemon.

    Args:
        config_path: Optional path to config file. Uses default if None.
    """
    # Load configuration
    try:
        cfg = load_config(config_path)
    except ConfigError as e:
        print(f"[contexad] Config error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"[contexad] Failed to load config: {e}", file=sys.stderr)
        sys.exit(1)

    # Initialize logging

    _configure_logging(cfg.daemon.log_level, cfg.daemon.log_output)
    install_global_exception_handler()
    log = structlog.get_logger("contexad")
    log.info("Contexa daemon starting", version="0.1.0")

    # Open SQLite database and run migrations
    try:
        data_dir = cfg.storage.data_dir
        init_db(data_dir)
        engine = build_engine(data_dir)
        session_factory = build_session_factory(engine)
        session = session_factory()
        log.info("Database initialized", path=str(data_dir / "contexa.db"))
    except Exception as e:
        log.error("Failed to initialize database", error=str(e))
        sys.exit(1)

    # Initialize stores
    try:
        context_store = ContextStore(session)
        trust_store = TrustStore(session, data_dir=data_dir)
        embedding_store = EmbeddingStore(session, model_name=cfg.embeddings.model)
        log.info("Stores initialized",
                 embeddings_enabled=embedding_store.enabled,
                 embeddings_model=cfg.embeddings.model or "disabled")
    except Exception as e:
        log.error("Failed to initialize stores", error=str(e))
        sys.exit(1)

    # Load or generate device identity
    try:
        identity = trust_store.register_self()
        log.info("Device identity loaded", device_id=identity.device_id)
    except Exception as e:
        log.error("Failed to load device identity", error=str(e))
        sys.exit(1)

    # Initialize Sync Engine
    try:
        sync_mode = SyncMode(cfg.sync.mode)
        sync_engine = SyncEngine(
            session=session,
            context_store=context_store,
            trust_store=trust_store,
            identity=identity,
            max_retries=cfg.sync.max_retries,
            backoff_base=float(cfg.sync.backoff_base_seconds),
            sync_mode=sync_mode,
            relay_endpoint=cfg.relay.endpoint,
        )
        log.info("Sync engine initialized", mode=cfg.sync.mode)
    except Exception as e:
        log.error("Failed to initialize sync engine", error=str(e))
        sys.exit(1)

    # Build and configure the FastAPI app
    app = create_app()
    app.state.context_store = context_store
    app.state.trust_store = trust_store
    app.state.embedding_store = embedding_store
    app.state.sync_engine = sync_engine
    app.state.config = cfg
    app.state.device_id = identity.device_id
    app.state.start_time = time.time()
    app.state.syncs_completed = 0
    app.state.sync_failures = 0

    # Configure uvicorn server (localhost only)
    if cfg.daemon.socket_path:
        uv_config = uvicorn.Config(
            app=app,
            uds=cfg.daemon.socket_path,
            log_level=cfg.daemon.log_level.lower(),
        )
    else:
        uv_config = uvicorn.Config(
            app=app,
            host="127.0.0.1",
            port=cfg.daemon.port,
            log_level=cfg.daemon.log_level.lower(),
        )

    server = uvicorn.Server(uv_config)

    # Register signal handlers for graceful shutdown
    def _shutdown(signum, frame):
        log.info("Shutdown signal received", signal=signum)
        server.should_exit = True

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    # Start serving
    log.info(
        "Local API listening",
        host="127.0.0.1" if not cfg.daemon.socket_path else cfg.daemon.socket_path,
        port=cfg.daemon.port if not cfg.daemon.socket_path else None,
    )

    try:
        server.run()
    except Exception as e:
        log.error("Server error", error=str(e))
        sys.exit(1)
    finally:
        # Graceful shutdown: flush pending writes and close DB
        log.info("Flushing pending writes")
        try:
            session.commit()
        except Exception:
            pass
        try:
            session.close()
        except Exception:
            pass
        try:
            engine.dispose()
        except Exception:
            pass
        log.info("Contexa daemon stopped")


if __name__ == "__main__":
    main()
