"""
Data providers for PoE2 game data.

Two complementary data sources, in priority order:
1. Local extraction (FreshDataProvider): files in data/extracted/ that the
   user populated themselves via scripts/extract_poe2_data.py.
2. Centralized distribution (data_distributor): downloads HivemindMinion's
   maintained data bundle from this repo's GitHub Releases. Closes #53 by
   ensuring pip-installed users get usable data without a manual extraction
   step.

Per CLAUDE.md data policy, both sources trace back to extraction from a
licensed PoE2 install. No third-party wiki / scraped data.
"""

from .fresh_data_provider import FreshDataProvider, get_fresh_data_provider
from . import data_distributor

__all__ = [
    'FreshDataProvider',
    'get_fresh_data_provider',
    'data_distributor',
]
