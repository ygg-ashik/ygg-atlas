"""Plugin discovery: every subpackage of app.sources exposing SOURCE is a data source.

A plugin whose required env is missing is skipped (logged), never fatal — the
platform runs with whatever sources are configured.
"""

import importlib
import pkgutil
from functools import cache

import structlog

from app.sources.base import (
    Connector,
    ConnectorError,
    ConnectorNotConfiguredError,
    SourcePlugin,
)

logger = structlog.get_logger()


def _discover() -> dict[str, SourcePlugin]:
    plugins: dict[str, SourcePlugin] = {}
    for module_info in pkgutil.iter_modules(__path__):
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


@cache
def get_plugins() -> dict[str, SourcePlugin]:
    return _discover()


def get_connector(source_id: str) -> Connector:
    plugin = get_plugins().get(source_id)
    if plugin is None:
        raise ConnectorNotConfiguredError(
            f"Data source '{source_id}' is not configured or does not exist"
        )
    return plugin.connector()


def reset_plugins() -> None:
    """Test helper: force re-discovery and drop cached connectors."""
    if get_plugins.cache_info().currsize:
        for plugin in get_plugins().values():
            plugin.reset()
    get_plugins.cache_clear()


__all__ = [
    "Connector",
    "ConnectorError",
    "ConnectorNotConfiguredError",
    "SourcePlugin",
    "get_connector",
    "get_plugins",
    "reset_plugins",
]
