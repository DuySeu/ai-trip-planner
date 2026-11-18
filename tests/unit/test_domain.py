from __future__ import annotations

from typing import get_args

from utils.domain import SEARCH_DOMAINS, SearchTask


def test_every_search_task_has_an_allowlist_entry():
    assert set(SEARCH_DOMAINS) == set(get_args(SearchTask))


def test_allowlist_entries_are_bare_domains():
    for task, domains in SEARCH_DOMAINS.items():
        for domain in domains:
            assert "/" not in domain and ":" not in domain and "." in domain, (task, domain)
        assert len(domains) == len(set(domains)), task
