"""Autonomous on-demand NBA evidence workflow for the isolated Telegram bot.

One /analyze is the trigger: reply with the immutable model forecast first,
then deliver fresh, source-labeled roster evidence and attempt the prospective
player-minutes collection automatically. Never change the original forecast or
claim an uncalibrated player model was applied. All source work is bounded.
"""
import asyncio
import html
import time

from hybrid_engine.current_roster import context_for,render_review
from hybrid_engine.data import local_path
from hybrid_engine.player_inputs import collect
from hybrid_engine.elite_render import split_blocks


def admission(snapshot,now):
    """Only a truly future NBA match gets present-day live roster observations."""
    if not isinstance(snapshot,dict) or snapshot.get('league')!='NBA':
        return 'NOT_AN_NBA_SNAPSHOT'
    start=snapshot.get('fixture_start_utc')
    if type(start) is not int or start<=now:
        return 'MATCH_ALREADY_STARTED_NO_PREMATCH_BACKFILL'
    try:
        context_for(snapshot)
    except (ValueError,KeyError,TypeError):
        return 'SNAPSHOT_OR_SOURCE_IDENTITY_UNVERIFIED'
    return 'FUTURE_FIXTURE_VERIFIED_CONTEXT'


async def collect_auto(snapshot,reviewer,assets,directory,*,now=None,
                       review_call=None,input_call=None,
                       roster_timeout=20,input_timeout=55):
    """Return an honest append-only sidecar; source failures never block score."""
    now=int(time.time()) if now is None else now
    gate=admission(snapshot,now)
    result=dict(format='AUTO_NBA_PLAYER_OBSERVATION_V1',
        status='BLOCKED',reason=None,roster_report=None,
        player_input_status='NOT_ATTEMPTED',player_input_reason=None,
        forecast_changed=False,model_coefficients_applied=False,
        calibration_status='NOT_CALIBRATED',production_changed=False,
        original_forecast_digest_verified=False)
    if gate!='FUTURE_FIXTURE_VERIFIED_CONTEXT':
        result['reason']=gate
        return result
    context=context_for(snapshot)
    result['original_forecast_digest_verified']=True
    reviewer_call=review_call or reviewer.review
    try:
        review=await asyncio.wait_for(
            asyncio.to_thread(reviewer_call,context),timeout=roster_timeout)
        if (review.get('fixture_id')!=snapshot['fixture_id'] or
            review.get('original_snapshot_sha256')!=context['original_snapshot_sha256'] or
            review.get('fixture_start_utc')!=snapshot['fixture_start_utc']):
            raise ValueError('AUTOMATIC_ROSTER_FORECAST_BINDING')
        result['status']='ROSTER_OBSERVED'
        result['roster_status']=review.get('status')
        result['roster_report']=render_review(review)
        result['espn_observations']=sum(r.get('source')=='ESPN' for r in review.get('records',[]))
        result['official_pdf_observations']=sum(r.get('source')=='NBA_OFFICIAL_PDF'
                                                 for r in review.get('records',[]))
        result['official_pdf_status']=review.get('official_code')
    except asyncio.TimeoutError:
        result.update(status='ROSTER_UNAVAILABLE',reason='ROSTER_SOURCE_TIME_BUDGET')
    except (ValueError,KeyError,TypeError,OSError):
        result.update(status='ROSTER_UNAVAILABLE',reason='ROSTER_SOURCE_OR_BINDING_UNAVAILABLE')

    if int(time.time()) >= snapshot['fixture_start_utc']-900:
        result['player_input_status']='NOT_ATTEMPTED_SAFE_WINDOW_CLOSED'
        return result
    if assets is None or directory is None:
        result['player_input_status']='NOT_CONFIGURED'
        return result
    try:
        collector=input_call or collect
        attempt=await asyncio.wait_for(asyncio.to_thread(
            collector,snapshot,assets,local_path(directory),reviewer=reviewer),timeout=input_timeout)
        result['player_input_status']=attempt.get('status','UNKNOWN')
        result['player_input_reason']=attempt.get('reason')
        result['real_minutes_sha256']=attempt.get('projection')
        result['model_coefficients_applied']=False
        result['original_forecast_digest_verified']=bool(
            attempt.get('forecast_changed') is False)
        if attempt.get('forecast_changed') is not False or attempt.get('production_changed') is not False:
            raise ValueError('PLAYER_AUTOMATION_FORECAST_CHANGED')
        if attempt.get('status') not in (
            'BLOCKED','PROSPECTIVE_MINUTES_ARCHIVED','EXISTING_MINUTES_REPLAY'):
            result['player_input_status']='UNVERIFIED_COLLECTION_STATUS'
            result['real_minutes_sha256']=None
    except asyncio.TimeoutError:
        result.update(player_input_status='SOURCE_TIME_BUDGET',player_input_reason='INPUT_COLLECTION_TIMEOUT')
    except (ValueError,KeyError,TypeError,OSError):
        result.update(player_input_status='SOURCE_OR_ARCHIVE_UNAVAILABLE',
                      player_input_reason='INPUT_COLLECTION_EXCEPTION')
    return result


def render_auto(result):
    """Keep source/score boundary explicit in the automatically sent follow-up."""
    esc=html.escape
    lines=['<b>OTOMATİK NBA OYUNCU / KADRO KONTROLÜ</b>',
        'Bu rapor için yeni Telegram komutu veya UserLAnd işlemi gerekmez.',
        'İlk skor tahmini korunur; oyuncu katsayıları bu skor hesabına uygulanmadı.']
    status=result.get('status','UNKNOWN')
    if status=='ROSTER_OBSERVED':
        lines.append('ESPN gözlemleri: '+str(result.get('espn_observations',0))+
            ' | NBA resmî PDF gözlemleri: '+str(result.get('official_pdf_observations',0)))
        lines.append('Resmî PDF durumu: '+esc(str(result.get('official_pdf_status') or 'DOĞRULANMADI')))
    else:
        lines.append('Güncel kaynak: '+esc(str(result.get('reason') or status))+
            '. Bu, oyuncuların sağlıklı veya eksiksiz olduğu anlamına gelmez.')
    observed=result.get('player_input_status','NOT_ATTEMPTED')
    lines.append('Gerçek dakika paketi: '+esc(str(observed)))
    if result.get('player_input_reason'):
        lines.append('Engel: '+esc(str(result['player_input_reason'])))
    if observed in ('PROSPECTIVE_MINUTES_ARCHIVED','EXISTING_MINUTES_REPLAY'):
        lines.append('Gerçek dakika paketi kaydedildi; bağımsız kalibrasyon ve skora etki henüz doğrulanmadı.')
    lines.append('Oyuncu etkili skor modeli: <b>BU ANALİZDE AKTİF DEĞİL</b>')
    return '\n'.join(lines)


def schedule_auto(app,league,report,chat_id,*,clock=time.time):
    """Schedule one automatic follow-up only after the original reply is sent.

    The 5-minute value is a duplicate-work cooldown, NOT an archive or model
    expiry. Future user commands can still display the stored forecast.
    """
    config=app.bot_data.get('auto_nba_player_pipeline')
    if (league.upper()!='NBA' or not isinstance(config,dict) or
            chat_id!=config.get('chat_id') or report.get('status')!='ANALYSIS_OK'):
        return False
    snapshot=report.get('snapshot')
    now=int(clock())
    if admission(snapshot,now)!='FUTURE_FIXTURE_VERIFIED_CONTEXT':
        return False
    fid=snapshot['fixture_id']
    attempts=app.bot_data.setdefault('auto_nba_attempt_clocks',{})
    previous=attempts.get(fid)
    cooldown=config.get('cooldown_seconds',300)
    if previous is not None and 0<=now-previous<cooldown:
        return False
    attempts[fid]=now
    # Keep a bounded in-memory receipt of actual automation activity, rather
    # than mistakenly displaying the independent research worker status.
    state=app.bot_data
    state['auto_nba_last_attempt']=dict(
        format='AUTO_NBA_COLLECTION_RUNTIME_V1',fixture_id=fid,
        scheduled_at_utc=now,status='SCHEDULED',player_input_status='NOT_STARTED',
        forecast_changed=False,model_coefficients_applied=False,
        telegram_followup_delivery='NOT_ATTEMPTED')

    async def work():
        receipt=state['auto_nba_last_attempt']
        receipt['status']='RUNNING'
        try:
            result=await collect_auto(snapshot,config['reviewer'],config['assets'],
                                     config['directory'])
            receipt.update(status='DATA_COLLECTION_FINISHED',
                completed_at_utc=int(clock()),
                roster_status=result.get('roster_status') or result['status'],
                player_input_status=result.get('player_input_status'),
                player_input_reason=result.get('player_input_reason'),
                forecast_changed=False,model_coefficients_applied=False)
            await send_auto(app.bot,chat_id,result)
            receipt['telegram_followup_delivery']='SEND_RETURNED_NOT_INDEPENDENTLY_VERIFIED'
            receipt['status']='FOLLOWUP_SENT_NOT_INDEPENDENTLY_VERIFIED'
        except Exception as exc:
            # Never leak source exceptions, tokens or private paths to Telegram.
            import logging
            receipt.update(status='FAILED',error_class=type(exc).__name__,
                completed_at_utc=int(clock()),
                telegram_followup_delivery='NOT_VERIFIED')
            logging.getLogger(__name__).warning('Autonomous NBA evidence unavailable: %s',
                                                type(exc).__name__)
            try:
                await app.bot.send_message(chat_id=chat_id,
                    text=('Otomatik NBA kadro/oyuncu incelemesi tamamlanamadı. '
                          'Bu durum oyuncuların eksiksiz olduğu anlamına gelmez. '
                          'İlk skor tahmini değiştirilmedi.'),
                    disable_web_page_preview=True)
            except Exception:
                logging.getLogger(__name__).warning('NBA evidence failure notice could not be sent')
    app.create_task(work())
    return True


async def send_auto(bot,chat_id,result,*,limit=3000):
    """Automatic continuation without another command; no fabricated delivery receipt."""
    summary=render_auto(result)
    await bot.send_message(chat_id=chat_id,text=summary,parse_mode='HTML',
                           disable_web_page_preview=True)
    roster=result.get('roster_report')
    if roster:
        for block in split_blocks(roster.splitlines(),limit=limit):
            await bot.send_message(chat_id=chat_id,text=block,parse_mode='HTML',
                                   disable_web_page_preview=True)
