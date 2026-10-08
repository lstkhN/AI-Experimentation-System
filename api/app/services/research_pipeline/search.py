"""Search stage: provider abstraction without evidence promotion."""
def search(provider, query: str, *, max_results: int = 10):
    """Search using the provider contract's ``max_results`` keyword."""
    return provider.search(query, max_results=max_results)
