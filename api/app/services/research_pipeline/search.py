"""Search stage: provider abstraction without evidence promotion."""
def search(provider, query: str, *, limit: int = 10):
    return provider.search(query, limit=limit)
