"""ugcguard: trust boundaries inside a website for agentic browsers."""

from .detect import detect
from .dom import Doc
from .regions import Region, RegionMap

__all__ = ["Doc", "Region", "RegionMap", "detect"]
__version__ = "0.1.0"
