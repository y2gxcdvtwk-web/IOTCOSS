from typing import Any


NECK_FORWARD_THRESHOLD = 120.0


def normalize_posture_content(content: Any) -> Any:
    """Use mCRA as the canonical source for the derived posture flag."""
    if not isinstance(content, dict) or "mCRA" not in content:
        return content
    try:
        mcra = float(content["mCRA"])
    except (TypeError, ValueError):
        return content
    normalized = dict(content)
    normalized["neck_forward"] = mcra >= NECK_FORWARD_THRESHOLD
    return normalized
