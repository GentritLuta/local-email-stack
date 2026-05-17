"""Sourcing engine registry.

Each engine module registers itself in REGISTRY via the @register decorator.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Type

REGISTRY: dict[str, Type["SourcingEngine"]] = {}


def register(name: str) -> Callable[[Type["SourcingEngine"]], Type["SourcingEngine"]]:
    def decorator(cls: Type["SourcingEngine"]) -> Type["SourcingEngine"]:
        REGISTRY[name] = cls
        cls.name = name
        return cls
    return decorator


@dataclass
class Lead:
    """Minimal lead shape returned by every engine.

    The enricher fills in everything else from this seed.
    """
    source: str                          # e.g. "twitter_profile", "local_business"
    source_id: str                       # stable identifier within that source
    handle: str = ""                     # display handle (e.g. @vitalik_eth)
    display_name: str = ""
    bio: str = ""
    url: str = ""                        # canonical profile URL
    location: str = ""
    language: str = ""
    follower_count: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def core_json(self) -> str:
        return json.dumps(asdict(self), default=str)


class SourcingEngine:
    """Base class. Every concrete engine implements `search`."""
    name: str = ""

    async def search(self, config: dict) -> list[Lead]:
        raise NotImplementedError

    async def fetch_profile(self, source_id: str) -> dict:
        """Optional — engines that can return richer profile data should override."""
        return {}


# Import all engine modules so they register on app start.
# Each import triggers @register(...) at module load.
from . import local_business        # noqa: E402, F401
from . import twitter_profile       # noqa: E402, F401
from . import youtube_channel       # noqa: E402, F401
from . import farcaster_creator     # noqa: E402, F401
from . import reddit_user           # noqa: E402, F401
from . import github_developer      # noqa: E402, F401
from . import linkedin_via_google   # noqa: E402, F401
from . import instagram_profile     # noqa: E402, F401
from . import tiktok_creator        # noqa: E402, F401
from . import bluesky_user          # noqa: E402, F401
from . import producthunt_maker     # noqa: E402, F401
from . import hackernews_hiring     # noqa: E402, F401
