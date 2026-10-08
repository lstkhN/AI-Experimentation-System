"""Claim extraction boundary; claims remain unverified candidates."""
def extract_claims(document: dict) -> list[dict]:
    text = document.get("text", "").strip()
    return [{"claim": text, "url": document.get("url"), "status": "candidate"}] if text else []
