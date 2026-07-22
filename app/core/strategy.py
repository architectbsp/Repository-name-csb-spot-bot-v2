"""
Backward-compatible Strategy export.

The classic dip-recovery logic lives in
``app.core.strategies.dip_hunter.DipHunterStrategy``. New code should
import from ``app.core.strategies`` and prefer named strategy classes.
"""

from app.core.strategies.dip_hunter import DipHunterStrategy as Strategy

__all__ = ["Strategy"]
