"""Layered delivery evidence. User reports, screenshots and API receipts are distinct."""
from html.parser import HTMLParser
import time
from urllib.parse import urlsplit

from core.team_identity import digest


class PlainHTML(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.parts=[]
    def handle_data(self,data):self.parts.append(data)


def plaintext(text,mode):
    if mode!='HTML':return text
    parser=PlainHTML();parser.feed(text);parser.close();return ''.join(parser.parts)


def official_endpoint(url,bot_id,method):
    p=urlsplit(url)
    return bool(p.scheme=='https' and p.netloc=='api.telegram.org' and not p.query and not p.fragment and
        p.path.startswith('/bot'+str(bot_id)+':') and p.path.rsplit('/',1)[-1]==method and len(p.path.split('/'))==3)


def evidence_report(events,*,user_report=None,screenshots=(),asof_utc=None):
    """No inference of technical fields from a screenshot or a user's narrative.

    Imported journals are local evidence, not independent Telegram signatures.
    Their file hash and ingestion source must accompany any published report.
    """
    now=int(time.time()) if asof_utc is None else asof_utc
    commands={e['update_id']:e for e in events if e.get('kind')=='COMMAND_RECEIVED'}
    accepted=[];excluded=[]
    for e in events:
        if e.get('kind')!='DELIVERY_ACCEPTED':continue
        command=commands.get(e.get('update_id'));reasons=[]
        if e.get('transport')!='OFFICIAL_TELEGRAM_BOT_API':reasons.append('MOCK_OR_UNATTESTED_TRANSPORT')
        if not e.get('dedicated_bot_identity_verified'):reasons.append('BOT_IDENTITY_UNVERIFIED')
        if not command or command.get('is_bot') is not False or command.get('chat_id')!=e.get('chat_id'):
            reasons.append('AUTHORIZED_HUMAN_COMMAND_UNVERIFIED')
        if not e.get('expected_chat_matches'):reasons.append('CHAT_UNVERIFIED')
        if not e.get('response_content_matches_request'):reasons.append('CONTENT_INTEGRITY_UNVERIFIED')
        sent=e.get('telegram_sent_at_utc');ack=e.get('ack_at_utc')
        if (type(sent) is not int or type(ack) is not int or not 0<sent<=ack+30 or ack>now or
            not command or type(command.get('user_message_at_utc')) is not int or
            not command['user_message_at_utc']<=sent+30):reasons.append('DELIVERY_CLOCK_UNVERIFIED')
        if type(e.get('telegram_message_id')) is not int or e['telegram_message_id']<=0:reasons.append('MESSAGE_ID_UNVERIFIED')
        if reasons:excluded.append(dict(update_id=e.get('update_id'),reasons=reasons))
        else:accepted.append(dict(update_id=e['update_id'],command=command['command'],
            chat_sha256=digest(e['chat_id']),message_id=e['telegram_message_id'],sent_at_utc=sent,
            response_sha256=e.get('response_sha256'),message_sha256=e['message_sha256']))
    # Screenshot documents are references to supplied artifacts, not manufactured API receipts.
    images=[dict(artifact_sha256=s['artifact_sha256'],visible_fields=s.get('visible_fields',{}),
        level='VISUAL_ONLY_NOT_API_OR_CHAT_ID_PROOF') for s in screenshots]
    complete_analysis=[]
    for update in {e['update_id'] for e in accepted if e['command']=='/analyze'}:
        parts=[e for e in events if e.get('record_type')=='TELEGRAM_ANALYSIS_DELIVERY' and e.get('update_id')==update and e.get('status')=='TELEGRAM_ACCEPTED']
        counts={e.get('part_count') for e in parts};indices={e.get('part_index') for e in parts}
        api_ids={e['message_id'] for e in accepted if e['update_id']==update}
        if (len(counts)==1 and type(next(iter(counts))) is int and next(iter(counts))>0 and
            len(parts)==next(iter(counts)) and indices==set(range(next(iter(counts)))) and
            {e.get('telegram_message_id') for e in parts}<=api_ids):complete_analysis.append(update)
    return dict(format='TELEGRAM_LAYERED_EVIDENCE_V1',
        status='TECHNICAL_API_EVIDENCE_VERIFIED' if accepted else 'USER_REPORTED_TECHNICAL_E2E_BLOCKED' if user_report else 'BLOCKED',
        user_report=user_report,screenshot_evidence=images,api_verified_messages=len(accepted),api_verified=accepted,
        excluded=excluded,actual_telegram_delivery_verified=bool(accepted),
        complete_analysis_updates=sorted(complete_analysis),
        complete_command_suite_verified=bool(complete_analysis) and set(x['command'] for x in accepted)>={'/nba','/analyze','/accuracy','/compare'},
        independent_server_signature=False,production_accessed=False)
