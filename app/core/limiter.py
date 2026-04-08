"""
Rate limiter singleton.

Defined here (not in main.py) to avoid circular imports when routers
need to reference the limiter instance.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

# Global default: 60 requests / minute per IP.
# Individual endpoints can override with a stricter @limiter.limit() decorator.
limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])
