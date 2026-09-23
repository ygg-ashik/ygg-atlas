"""Plugin discovery: every subpackage of app.sources exposing SOURCE is a data source.

A plugin whose required env is missing is skipped (logged), never fatal — the
platform runs with whatever sources are configured.
"""

import importlib
import pkgutil

import structlog

from app.sources.base import Connector, ConnectorError, ConnectorNotConfigured, SourcePlugin

logger = structlog.get_logger()

_plugins: dict[str, SourcePlugin] | None = None


def _discover() -> dict[str, SourcePlugin]:
    import app.sources as pkg

    plugins: dict[str, SourcePlugin] = {}
    for module_info in pkgutil.iter_modules(pkg.__path__):
        if not module_info.ispkg:
            continue
        module = importlib.import_module(f"app.sources.{module_info.name}.manifest")
        plugin: SourcePlugin = module.SOURCE
        if not plugin.is_configured():
            logger.info(
                "sources.skipped_unconfigured",
                source=plugin.id,
                required_env=plugin.required_env,
            )
            continue
        if plugin.id in plugins:
            raise ValueError(f"Duplicate source id '{plugin.id}'")
        plugins[plugin.id] = plugin
    logger.info("sources.enabled", sources=sorted(plugins))
    return plugins


def get_plugins() -> dict[str, SourcePlugin]:
    global _plugins
    if _plugins is None:
        _plugins = _discover()
    return _plugins


def get_connector(source_id: str) -> Connector:
    plugin = get_plugins().get(source_id)
    if plugin is None:
        raise ConnectorNotConfigured(
            f"Data source '{source_id}' is not configured or does not exist"
        )
    return plugin.connector()


def reset_plugins() -> None:
    """Test helper: force re-discovery and drop cached connectors."""
    global _plugins
    if _plugins:
        for plugin in _plugins.values():
            plugin.reset()
    _plugins = None


__all__ = [
    "Connector",
    "ConnectorError",
    "ConnectorNotConfigured",
    "SourcePlugin",
    "get_connector",
    "get_plugins",
    "reset_plugins",
]
