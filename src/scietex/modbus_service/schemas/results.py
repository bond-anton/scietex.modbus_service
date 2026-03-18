"""Schemas for task results."""

import msgspec


class CountResult(msgspec.Struct, frozen=True):
    """Count result schema."""

    count: int


class StatusResult(msgspec.Struct, frozen=True):
    """Status result schema."""

    status: bool
