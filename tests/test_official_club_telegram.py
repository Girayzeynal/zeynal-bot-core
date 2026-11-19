"""Actual Telegram /kadro handler is registered in both app entrypoints."""
import asyncio
from types import SimpleNamespace

import pytest

from hybrid_engine import official_club_telegram as cmd


def test_parse_both_real_euroleague_match_pair_forms_and_all_leagues():
    for league,home,away in [
        ("EUROLEAGUE","Armani Olimpia Milan","Fenerbahce Tarfin Istanbul"),
        ("EUROLEAGUE","Zalgiris Kaunas","Panathinaikos AKTOR Athens"),
        ("NBA","Boston Celtics","Denver Nuggets"),
        ("EUROCUP","TOFAS Bursa","Cedevita Olimpija Ljubljana"),
    ]:
        q=f"/kadro {league} {home} vs {away}"
        r=cmd.parse_team_pair(q)
        assert r["home"]["official_name"]==home
        assert r["away"]["official_name"]==away
        assert r["fixture_start_utc"] is None
        assert r["league"]==league


def test_invalid_syntax_or_same_team_refused():
    for q in ("/kadro","/kadro NBA Boston Celtics","/kadro NBA Boston Celtics vs Boston Celtics"):
        with pytest.raises(ValueError):
            cmd.parse_team_pair(q)


def test_telegram_sends_two_club_sources_without_model_claim(monkeypatch):
    calls=[]
    async def reply(message,**kwargs):
        calls.append((message,kwargs))
    message=SimpleNamespace(
        text="/kadro EUROLEAGUE Zalgiris Kaunas vs Panathinaikos AKTOR Athens",
        reply_text=reply)
    update=SimpleNamespace(effective_message=message)
    seen=[]
    def fake(ctx,*,allow_no_fixture):
        seen.append((ctx,allow_no_fixture))
        return dict(status="TEAM_ONLY_OFFICIAL_SOURCE_REVIEW_NOT_FIXTURE_VERIFIED",
            rows=[
                dict(side="home",team="Zalgiris Kaunas",
                    official_site_url="https://zalgiris.lt/",
                    news_url="https://zalgiris.lt/naujienos",
                    status="OFFICIAL_NEWS_INDEX_OBSERVED_ONLY",
                    headlines=[]),
                dict(side="away",team="Panathinaikos AKTOR Athens",
                    official_site_url="https://www.paobc.gr/en/",
                    news_url="https://www.paobc.gr/en/news/",
                    status="OFFICIAL_NEWS_INDEX_OBSERVED_ONLY",
                    headlines=[])],
            model_input=False,injury_verified=False)
    monkeypatch.setattr(cmd,"read_fixture_club_news",fake)
    asyncio.run(cmd.kadro_command(update,None))
    assert len(calls)==1 and len(seen)==1
    assert seen[0][1] is True
    output=calls[0][0]
    assert "Zalgiris Kaunas" in output
    assert "Panathinaikos AKTOR Athens" in output
    assert "Maç kimliği" in output
    assert calls[0][1]["parse_mode"]=="HTML"


def test_unavailable_official_source_is_not_assigned_no_injuries(monkeypatch):
    async def run():
        sent=[]
        async def reply(msg,**kwargs):sent.append(msg)
        message=SimpleNamespace(
            text="/kadro NBA Boston Celtics vs Denver Nuggets",reply_text=reply)
        update=SimpleNamespace(effective_message=message)
        def no_source(*a,**kw):raise ValueError("SOURCE_UNAVAILABLE")
        monkeypatch.setattr(cmd,"read_fixture_club_news",no_source)
        await cmd.kadro_command(update,None)
        assert len(sent)==1
        assert "eksik oyuncusu olmadığı" in sent[0]
    asyncio.run(run())


def test_prod_and_testbot_install_same_telegram_command():
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    prod=(root/"main.py").read_text()
    test=(root/"hybrid_engine/test_bot.py").read_text()
    assert "install_kadro_command(app)" in prod
    assert "install_kadro_command(app,group=-50)" in test
