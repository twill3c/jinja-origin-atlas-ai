# -*- coding: utf-8 -*-
"""T-139: ja.wikipedia の取得は 429(Too Many Requests)で止まらず、待って取り直す。

月次の二回目の実行(run 34925557545)で、ランナーは手元より速く(3.3 件/秒)取りに行き、
約 680 件目で 429 が返って、再試行の無い fetch_one がその場で落ちた。**429 は障害ではなく
「速すぎる」という答え**なので、Retry-After(無ければ指数的に)だけ待って取り直す。
取り直しても 429 が続くときは、回数の上限で止める(黙って空の記事にしない)。
"""
import httpx
import pytest

import etl.fetch_wikipedia as fw

OK_BODY = {"query": {"pages": [{"title": "八幡神社", "pageid": 1,
                                "revisions": [{"revid": 42, "timestamp": "2026-01-01T00:00:00Z"}],
                                "extract": "由緒の本文"}]}}


def _client(responses):
    calls = []

    def handler(request):
        calls.append(request)
        status, headers = responses[min(len(calls) - 1, len(responses) - 1)]
        if status == 200:
            return httpx.Response(200, json=OK_BODY)
        return httpx.Response(status, headers=headers)

    return httpx.Client(transport=httpx.MockTransport(handler)), calls


@pytest.mark.unit
def test_t139_retries_after_429_and_returns_the_article(monkeypatch):
    slept = []
    monkeypatch.setattr(fw.time, "sleep", lambda s: slept.append(s))
    client, calls = _client([(429, {"Retry-After": "7"}), (429, {}), (200, {})])
    d = fw.fetch_one(client, "八幡神社")
    assert d is not None and d["revid"] == 42
    assert len(calls) == 3, "429 のあと取り直していない"
    assert slept[0] == 7, "Retry-After の秒数だけ待っていない"
    assert slept[1] > 0, "Retry-After が無いときも待っていない"


@pytest.mark.unit
def test_t139_gives_up_after_the_retry_limit(monkeypatch):
    monkeypatch.setattr(fw.time, "sleep", lambda s: None)
    client, calls = _client([(429, {})])
    with pytest.raises(httpx.HTTPStatusError):
        fw.fetch_one(client, "八幡神社")
    assert 2 <= len(calls) <= 10, f"取り直しの回数が上限を持たない: {len(calls)}"
