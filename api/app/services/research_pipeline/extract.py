"""Extract readable text while retaining the source URL."""
def extract(page: dict) -> dict:
    content = page.get("content", "")
    return {**page, "text": content if isinstance(content, str) else str(content)}
