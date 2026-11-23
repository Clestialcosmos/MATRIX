import hashlib


def normalize_activation_code(code: str) -> str:
    """Trim copy/paste whitespace while preserving the code's case and symbols."""
    return code.strip()


def hash_activation_code(code: str) -> str:
    normalized = normalize_activation_code(code)
    if not normalized:
        raise ValueError("Activation code is empty")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
