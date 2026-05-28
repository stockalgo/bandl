from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any


def coindcx_signature(body: dict[str, Any], api_secret: str) -> str:
    payload = json.dumps(body, separators=(",", ":"))
    return hmac.new(api_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
