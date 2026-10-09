import pytest

from gov_platform.regulatory_sources import SOURCE_CATALOG, _TextExtractor, _validate_official_url


def test_catalog_contains_only_official_government_domains():
    assert SOURCE_CATALOG
    for _jurisdiction, _title, url, domain in SOURCE_CATALOG:
        _validate_official_url(url)
        assert urlparse_host(url) == domain


def test_source_url_allowlist_rejects_non_https_and_untrusted_hosts():
    with pytest.raises(ValueError, match="not_allowlisted"):
        _validate_official_url("http://laws-lois.justice.gc.ca/eng/acts/c-15.31/")
    with pytest.raises(ValueError, match="not_allowlisted"):
        _validate_official_url("https://attacker.example/law")


def test_html_extractor_ignores_script_and_navigation_content():
    parser = _TextExtractor()
    parser.feed("<html><nav>Menu</nav><main>Official law text</main><script>secret()</script></html>")
    extracted = " ".join(parser.parts)
    assert "Official law text" in extracted
    assert "Menu" not in extracted
    assert "secret" not in extracted


def urlparse_host(url: str) -> str | None:
    from urllib.parse import urlparse

    return urlparse(url).hostname
