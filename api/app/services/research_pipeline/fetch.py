"""Fetch stage with explicit provenance."""
def fetch(fetcher, url: str) -> dict:
    result = fetcher(url)
    return {"url": url, "content": result, "fetched": True}
