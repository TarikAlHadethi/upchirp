"""Is a model reachable? Evals that need one skip cleanly when it is not (CI)."""

import os
import urllib.request


def model_available() -> bool:
    if os.environ.get("UPCHIRP_MODEL") == "anthropic":
        return bool(os.environ.get("ANTHROPIC_API_KEY"))
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    try:
        with urllib.request.urlopen(f"{host}/api/tags", timeout=2):
            return True
    except OSError:
        return False
