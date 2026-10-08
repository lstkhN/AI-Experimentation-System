from app.services.research_pipeline.cluster import cluster


def test_cluster_uses_canonical_url_over_caller_cluster_or_domain():
    clustered = cluster([
        {
            "url": "HTTPS://WWW.Example.test/report/?utm_source=newsletter#section",
            "source_cluster": "caller-override",
            "domain": "domain-override",
        },
        {"source_cluster": "legacy-cluster", "domain": "domain-override"},
        {"domain": "legacy-domain"},
    ])

    assert [item["source_cluster"] for item in clustered] == [
        "example.test",
        "legacy-cluster",
        "legacy-domain",
    ]
