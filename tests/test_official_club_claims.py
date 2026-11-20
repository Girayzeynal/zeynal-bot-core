"""Offline candidate extraction tests. Public text, not roster evidence."""
import pytest

from hybrid_engine.official_club_claims import injury_absence_candidates

EXPLICIT="Sakatlıkları bulunan Yiğitcan Saybir ile Efe Postel bu karşılaşmada forma giyemeyecek."

def test_precise_club_wording_extracts_two_names_without_verifying_them():
    text="TOFAŞ EuroCup deplasman haberi. "+EXPLICIT+" Takım hazırlıklarını tamamladı."
    result=injury_absence_candidates(text,club_key="eurocup_tofas")
    assert [r["player_name_text"] for r in result]==["Yiğitcan Saybir","Efe Postel"]
    assert all(r["reported_reason"]=="INJURY_IN_SOURCE_SENTENCE" for r in result)
    assert all(r["native_player_id"] is None and r["fixture_id"] is None for r in result)
    assert all(r["model_input"] is False and r["historical_prematch_eligibility"] is False for r in result)

def test_long_precise_club_sentence_is_not_ignored():
    intro=("Takım deplasman öncesi antrenmanlarını sürdürürken; "*12)
    result=injury_absence_candidates(intro+EXPLICIT,club_key="eurocup_tofas")
    assert len(result)==2

@pytest.mark.parametrize("text",[
    "Yiğitcan Saybir sakat görünüyor, Efe Postel hakkında açıklama yapılmadı.",
    "Yiğitcan Saybir ile Efe Postel kadroda yer almadı.",
    "Sakatlıkları bulunan Yiğitcan Saybir ile Efe Postel forma giyebilecek.",
    "Sakatlıkları bulunan Yiğitcan Saybir ile Efe Postel dün forma giydi.",
])
def test_vague_retrospective_or_positive_words_do_not_create_absence_claim(text):
    assert injury_absence_candidates(text,club_key="eurocup_tofas")==[]

def test_club_scope_never_reuses_tofas_pattern_for_nba_or_euroleague():
    assert injury_absence_candidates(EXPLICIT,club_key="nba_denver_nuggets")==[]
    assert injury_absence_candidates(EXPLICIT,club_key="euroleague_zalgiris")==[]

def test_duplicate_sentences_deduplicate_names():
    assert len(injury_absence_candidates(EXPLICIT+" "+EXPLICIT,club_key="eurocup_tofas"))==2

def test_source_text_budget_limits():
    with pytest.raises(ValueError):
        injury_absence_candidates("x"*8193,club_key="eurocup_tofas")
