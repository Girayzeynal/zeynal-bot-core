"""Synthetic presentation cases and existing PTB loopback; not real Telegram E2E."""
from copy import deepcopy
from html.parser import HTMLParser
import unittest

from core.team_identity import digest
from hybrid_engine.market_direction_ui import cards,brief,render,direction,reason,projection_mean,pages,order,MAX_CARDS
from hybrid_engine.telegram_premium_ui import compact_summary,keyboard,page_view,cache_report,direction_card_matches_snapshot
from hybrid_engine.intervals import sample_paths
from tests import test_current_market_review as synthetic

class DirectionCardTests(unittest.TestCase):
    def setUp(self):
        self.h=synthetic.CurrentReviewTests('runTest');self.h.setUp();self.addCleanup(self.h.doCleanups)
        self.view=self.h.review()
        self.forecast=self.h.dist.forecast

    def make(self,view=None):
        return cards(view or self.view,self.forecast,
            tipoff_utc=self.h.snap['fixture_start_utc'],fixture_id=self.h.snap['fixture_id'])

    def snapshot(self,card):
        return dict(fixture_id=card['fixture_id'],model_digest=card['model_digest'],
            prediction_generated_at_utc=card['prediction_utc'],fixture_start_utc=card['tipoff_utc'],
            home={'official_name':'Synthetic Home'},away={'official_name':'Synthetic Away'},
            prediction=self.forecast.summary(),intervals=self.h.snap['intervals'])

    def test_direction_probability_reliability_and_reason_have_approved_order(self):
        c=self.make()[0];text=brief(c)
        positions=[text.index(s) for s in ('MODEL YÖNÜ','Model olasılığı','Yönün güvenilirliği','Gerekçe')]
        self.assertEqual(positions,sorted(positions))
        self.assertIn('Henüz yeterince doğrulanmadı',text)
        self.assertIsNone(c['confidence_index']);self.assertFalse(c['selection_enabled'])

    def test_direction_follows_sample_frequencies_not_price_or_mean(self):
        v=deepcopy(self.view);r=v['rows'][0]
        r['conditional_regulation_probabilities']=dict(under=.38,push=0.,over=.62)
        r['line']=300.;r['prices']=dict(over=9.,under=1.01)
        c=self.make(v)[0]
        self.assertEqual(c['side'],'over');self.assertAlmostEqual(c['probability'],.62)
        self.assertIn('örneklerinde ÜST',reason(c));self.assertNotIn('üstünde',reason(c))

    def test_mean_gap_explanation_uses_exact_market_line(self):
        v=deepcopy(self.view);v['rows'][0].update(line=212.5,conditional_regulation_probabilities=dict(under=.38,push=0.,over=.62))
        c=self.make(v)[0];self.assertAlmostEqual(c['mean'],221.)
        self.assertEqual(direction(c),'ÜST 212,5');self.assertIn('8,5 sayı üstünde',reason(c))

    def test_neutral_or_push_dominant_mass_does_not_force_a_side(self):
        for p in [dict(under=.5,push=0.,over=.5),dict(under=.1,push=.8,over=.1)]:
            v=deepcopy(self.view);v['rows'][0]['conditional_regulation_probabilities']=p
            c=self.make(v)[0];self.assertIsNone(c['side'])
            self.assertEqual(direction(c),'BELİRGİN YÖN YOK');self.assertIsNone(c['probability'])

    def test_invalid_probabilities_fail_instead_of_fabricating_a_percentage(self):
        for p in [dict(under=.5,push=0.,over=.6),dict(under=-.1,push=0.,over=1.1),dict(under=True,push=0.,over=0.),dict(under=float('nan'),push=0.,over=1.)]:
            v=deepcopy(self.view);v['rows'][0]['conditional_regulation_probabilities']=p
            with self.subTest(p=p),self.assertRaises(ValueError):self.make(v)

    def test_integer_push_mass_is_visible_not_renormalized(self):
        v=deepcopy(self.view);v['rows'][0]['conditional_regulation_probabilities']=dict(under=.36,push=.02,over=.62)
        c=self.make(v)[0];text=render(c)
        self.assertIn('eşit skor: %2,0',text);self.assertAlmostEqual(c['probability'],.62)

    def test_every_price_card_warns_unknown_overtime_and_settlement_rules(self):
        for card in self.make():
            rendered=render(card)
            self.assertIn('SÖZLEŞME UYUMU DOĞRULANMADI',rendered)
            self.assertIn('bahis kazanma olasılığı değildir',rendered)
            self.assertIn('NORMAL SÜRE',rendered)
        winner=deepcopy(self.view)
        winner['rows'][0].update(market='WINNER',line=0.)
        self.assertIn('iki yönlü bahis piyasasındaki uzatma sonucuna otomatik aktarılmaz',
                      render(self.make(winner)[0]))

    def test_winner_uses_regulation_tie_and_does_not_invent_ot_winner(self):
        v=deepcopy(self.view);v['rows'][0].update(market='WINNER',line=0.,conditional_regulation_probabilities=dict(under=.315,push=.02,over=.665))
        c=self.make(v)[0];text=render(c)
        self.assertEqual(direction(c),'EV');self.assertIn('Normal süre eşitliği: %2,0',text)
        self.assertAlmostEqual(c['probability'],.665)

    def test_home_handicap_direction_does_not_reverse_the_home_line(self):
        v=deepcopy(self.view);v['rows'][0].update(market='HOME_HANDICAP',line=-9.,conditional_regulation_probabilities=dict(under=.503,push=.022,over=.475))
        c=self.make(v)[0];text=render(c)
        self.assertEqual(direction(c),'DEP KARŞILAR')
        self.assertIn('Ev sahibi handikabı · -9',text);self.assertAlmostEqual(c['mean'],3.)

    def test_total_team_quarter_and_half_means_come_from_frozen_projection(self):
        q=self.forecast.quarter_means
        for i in range(4):self.assertAlmostEqual(projection_mean(self.forecast,str(i+1)+'Q','TOTAL'),float(q[i].sum()))
        for part,section in [('1H',q[:2]),('2H',q[2:])]:
            self.assertAlmostEqual(projection_mean(self.forecast,part,'HOME'),float(section[:,0].sum()))
            self.assertAlmostEqual(projection_mean(self.forecast,part,'AWAY'),float(section[:,1].sum()))

    def test_old_price_keeps_raw_direction_but_is_not_current(self):
        v=deepcopy(self.view);v['decision_utc']+=301
        c=self.make(v)[0];self.assertFalse(c['current'])
        self.assertIn('ARŞİV MODEL YÖNÜ',render(c));self.assertIn('arşiv gözlemi',render(c))

    def test_post_tipoff_is_archival_even_with_provider_later_start(self):
        v=deepcopy(self.view);v['decision_utc']=self.h.snap['fixture_start_utc']
        c=self.make(v)[0];self.assertFalse(c['current']);self.assertTrue(c['post_tipoff'])
        self.assertIn('Maç başladı',render(c))

    def test_manual_transcription_is_not_current_native_evidence(self):
        v=deepcopy(self.view);v['source']['method']='MANUAL_SCREENSHOT'
        c=self.make(v)[0];self.assertFalse(c['current'])
        self.assertIn('MANUEL EKRAN AKTARIMI',render(c))

    def test_high_raw_probability_never_creates_high_confidence(self):
        v=deepcopy(self.view);v['rows'][0]['conditional_regulation_probabilities']=dict(under=.001,push=0.,over=.999)
        c=self.make(v)[0];text=render(c)
        self.assertIn('%99,9',text);self.assertIn('Henüz yeterince doğrulanmadı',text)
        self.assertNotIn('Yüksek güven',text);self.assertIsNone(c['confidence_index'])

    def test_book_prices_and_source_identity_are_not_blended(self):
        a=self.make()[0];b=deepcopy(a);b['bookmaker']=dict(id='other',name='Other')
        b['prices']=dict(under=1.5,over=2.7)
        rendered=pages([a,b])
        self.assertEqual(len(rendered),2)
        self.assertIn('2,7',next(t for t in rendered if 'Other' in t))
        self.assertEqual(a['prices'],self.view['rows'][0]['prices'])

    def test_source_and_fixture_labels_are_html_escaped(self):
        c=self.make()[0];c['bookmaker']['name']='<unsafe&>';c['provider']='<provider>'
        text=render(c);self.assertIn('&lt;unsafe&amp;&gt;',text);self.assertNotIn('<unsafe',text)

    def test_direction_rendering_does_not_change_samples_review_or_snapshot(self):
        before=(digest(self.view),digest(self.h.snap),sample_paths(self.forecast).tobytes())
        c=self.make();pages(c);brief(c[0])
        self.assertEqual((digest(self.view),digest(self.h.snap),sample_paths(self.forecast).tobytes()),before)

    def test_unavailable_view_does_not_invent_any_direction(self):
        self.assertEqual(cards({'rows':[]},self.forecast,
            tipoff_utc=self.h.snap['fixture_start_utc'],fixture_id=self.h.snap['fixture_id']),[])

    def test_current_quote_expiry_preserves_earliest_native_clock(self):
        c=self.make()[0]
        self.assertLessEqual(c['valid_until_utc'],self.h.snap['fixture_start_utc'])
        self.assertLessEqual(c['valid_until_utc'],self.view['source']['captured_at_utc']+300)

    def test_pages_have_explicit_display_budget_without_deleting_input(self):
        c=self.make()[0];values=[deepcopy(c) for _ in range(MAX_CARDS+1)]
        rendered=pages(values);self.assertEqual(len(rendered),MAX_CARDS+1)
        self.assertIn('Gösterim sınırı',rendered[-1]);self.assertEqual(len(values),MAX_CARDS+1)

    def test_order_is_source_display_priority_not_probability_ranking(self):
        a=self.make()[0];a['provider']='ESPN';a['probability']=.99
        b=deepcopy(a);b['provider']='The Odds API';b['probability']=.51
        self.assertEqual(order([a,b])[0]['provider'],'The Odds API')

    def test_card_html_tags_are_balanced_and_fit_telegram(self):
        class Tags(HTMLParser):
            def __init__(self):super().__init__();self.stack=[]
            def handle_starttag(self,tag,attrs):self.stack.append(tag)
            def handle_endtag(self,tag):
                if not self.stack or self.stack.pop()!=tag:raise AssertionError('UNBALANCED_HTML')
        for text in pages(self.make()):
            parser=Tags();parser.feed(text);self.assertEqual(parser.stack,[])
            self.assertLessEqual(len(text.encode('utf-16-le'))//2,3200)

    def test_compact_summary_has_direction_and_keeps_sources_in_detail(self):
        c=self.make()[0];s=self.snapshot(c);text=compact_summary(s,[],replayed=True,direction_card=c)
        self.assertIn('MODEL YÖNÜ',text);self.assertIn('Model olasılığı',text)
        self.assertIn('Henüz yeterince doğrulanmadı',text);self.assertIn('221.0',text)
        self.assertNotIn('ELITE_HYBRID_',text);self.assertLess(len(text.encode('utf-16-le'))//2,2500)

    def test_cross_fixture_model_time_or_mean_cannot_enter_summary(self):
        c=self.make()[0];s=self.snapshot(c)
        for change in [dict(fixture_id='other'),dict(model_digest='f'*64),dict(prediction_utc=c['prediction_utc']-1),dict(mean=c['mean']+1),dict(period='1Q')]:
            bad=dict(c,**change)
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,'SUMMARY_DIRECTION'):compact_summary(s,[],replayed=True,direction_card=bad)

    def test_later_research_market_card_is_not_attributed_to_first_forecast(self):
        c=self.make()[0];s=self.snapshot(c)
        self.assertTrue(direction_card_matches_snapshot(s,c))
        # Reproduce real Telegram fault at telegram_premium_ui.py:26:
        # current quotes were evaluated with a newer model context, not with
        # the immutable first forecast. The safe call-site passes None.
        for altered in (
            dict(model_digest='f'*64),
            dict(prediction_utc=c['prediction_utc']+600),
            dict(mean=c['mean']+1.0),
            dict(fixture_id='cross-match'),
            dict(tipoff_utc=c['tipoff_utc']+60),
        ):
            current_research=dict(c,**altered)
            self.assertTrue(current_research['current'])
            self.assertFalse(direction_card_matches_snapshot(s,current_research))
            summary=compact_summary(s,[],replayed=True,
                direction_card=(current_research if
                    direction_card_matches_snapshot(s,current_research) else None))
            self.assertIn('Güncel doğrulanmış barem yok',summary)
            self.assertNotIn('MODEL YÖNÜ:',summary)
            self.assertIn('221.0',summary)
        # Safety invariant is retained: direct accidental card attachment
        # still fails instead of silently borrowing an unrelated direction.
        with self.assertRaisesRegex(ValueError,'SUMMARY_DIRECTION'):
            compact_summary(s,[],replayed=True,
                direction_card=dict(c,model_digest='f'*64))

    def test_stale_card_never_becomes_main_screen_direction(self):
        c=self.make()[0];c['current']=False;s=self.snapshot(c)
        text=compact_summary(s,[],replayed=True,direction_card=c)
        self.assertNotIn('MODEL YÖNÜ:',text);self.assertIn('Güncel doğrulanmış barem yok',text)

class PaginationAndCacheTests(unittest.TestCase):
    def entry(self):
        return dict(summary='SUMMARY',sections={'market':'FIRST','audit':'AUDIT'},
            section_pages={'market':['FIRST','SECOND']},tipoff_utc=1000,quote_valid_until_utc=500)

    def test_one_callback_selects_one_page_without_message_spam(self):
        e=self.entry()
        self.assertEqual(page_view(e,'market',1,now=400),('SECOND',2))

    def test_out_of_range_and_negative_pages_are_rejected(self):
        for n in [-1,2,True]:
            with self.subTest(n=n),self.assertRaises(ValueError):page_view(self.entry(),'market',n,now=400)

    def test_expired_prices_are_explicit_on_cached_display(self):
        text,_=page_view(self.entry(),'market',0,now=501)
        self.assertIn('Arşiv görünümü',text);self.assertIn('yeniden sorgulanmadı',text)

    def test_stale_market_page_loses_current_header_and_current_direction(self):
        market=('📈 <b>V3 ARAŞTIRMA ADAYI | ZAMAN DAMGALI FİYAT GÖZLEMİ</b>\\n'
                '🎯 <b>MODEL YÖNÜ: ÜST 221,5</b>\\n'
                'Fiyata erişim: 23.11.2026 08:40:09 TSİ')
        e=self.entry()
        e['sections']['market']=market
        e['section_pages']['market']=[market]
        before=e['section_pages']['market'][0]
        fresh,_=page_view(e,'market',0,now=499)
        self.assertIn('ZAMAN DAMGALI FİYAT GÖZLEMİ',fresh)
        self.assertNotIn('ARŞİV PİYASA GÖZLEMİ — GÜNCEL ORAN DEĞİL',fresh)
        stale,_=page_view(e,'market',0,now=500)
        self.assertIn('ARŞİV V3 PİYASA GÖZLEMİ',stale)
        self.assertIn('ARŞİV MODEL YÖNÜ',stale)
        self.assertNotIn('GÜNCEL ARAŞTIRMA ADAYI | DOĞRULANMIŞ FİYATLAR',stale)
        self.assertNotIn('🎯 <b>MODEL YÖNÜ:',stale)
        self.assertIn('GÜNCEL ORAN DEĞİL',stale)
        self.assertEqual(e['section_pages']['market'][0],before)

    def test_cached_post_tipoff_summary_never_looks_like_new_prematch(self):
        text,_=page_view(self.entry(),'summary',0,now=1000)
        self.assertIn('Maç başladı',text);self.assertIn('SUMMARY',text)

    def test_keyboard_pagination_keeps_callback_ids_bounded(self):
        markup=keyboard('a'*12,section='market',page=5,pages=128)
        self.assertTrue(all(len(b.callback_data.encode())<=64 for row in markup.inline_keyboard for b in row))
        self.assertIn('zui:'+'a'*12+':market:6',[b.callback_data for row in markup.inline_keyboard for b in row])

    def test_cache_evicts_old_report_by_count(self):
        cache={};cache_report(cache,'one',self.entry(),max_count=1)
        cache_report(cache,'two',self.entry(),max_count=1)
        self.assertEqual(list(cache),['two'])

    def test_oversize_cache_entry_does_not_delete_existing_reports(self):
        cache={'one':self.entry()};before=deepcopy(cache)
        with self.assertRaises(ValueError):cache_report(cache,'two',self.entry(),max_bytes=2)
        self.assertEqual(cache,before)

    def test_cache_budget_counts_both_detail_text_and_paginated_text(self):
        e=dict(summary='s',sections={'market':'x'*20},section_pages={'market':['x'*20]})
        with self.assertRaises(ValueError):cache_report({},'one',e,max_bytes=30)

if __name__=='__main__':unittest.main()
