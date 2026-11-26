"""Private journal binding for the isolated /accuracy all acceptance check."""
import os
import re
import time

from core.team_identity import digest
from hybrid_engine.telegram_evidence import evidence_report


def release_sha():
    value = os.getenv('ZEYNAL_RELEASE_SHA', '')
    return value if re.fullmatch(r'[0-9a-f]{40}', value) else None


def accuracy_key(update_id):
    return f'accuracy-all:{update_id}'


async def send_accuracy(update, message, parts, receipt, write):
    """Record the expected message count and the parts Telegram acknowledged."""
    record = dict(kind='ACCURACY_ALL_DELIVERY', release_sha=release_sha(),
                  update_id=update.update_id, request_sha256=digest(message.text),
                  chat_id=update.effective_chat.id, expected_parts=len(parts), parts=[],
                  report=receipt, prepared_at_utc=int(time.time()))
    try:
        for part in parts:
            sent = await message.reply_text(part, parse_mode=None, disable_web_page_preview=True)
            record['parts'].append(dict(message_id=sent.message_id, request_text_sha256=digest(part)))
    finally:
        record['completed_at_utc'] = int(time.time())
        if record['expected_parts'] != len(record['parts']):
            record['send_status'] = 'INCOMPLETE'
        else:
            record['send_status'] = 'ALL_PARTS_RETURNED'
        await write(accuracy_key(update.update_id), record)


def sanitized_error(value):
    if type(value) is str and re.fullmatch(r'[A-Z][A-Z_0-9]{1,100}(?: \(SQLITE_[A-Z_]+/[0-9]{1,6}\))?',value):
        return value
    return 'DETAIL_UNAVAILABLE'


def inspect_accuracy(record, command, acknowledgments, *, expected_release, now):
    """Only local, hash-checked receipts are exported as aggregate evidence."""
    if not record:
        return dict(status='NOT_OBSERVED')
    if record.get('kind') != 'ACCURACY_ALL_DELIVERY':
        raise ValueError('ACCURACY_DELIVERY_KIND_INVALID')
    parts = record['parts']
    expected = record['expected_parts']
    from hybrid_engine.unified_results_view import LEAGUES
    leagues = {}
    for league in LEAGUES:
        row = record['report']['leagues'][league]
        if row['status'] not in ('READ', 'FAILED') or type(row['elapsed_ms']) is not int or row['elapsed_ms'] < 0:
            raise ValueError('ACCURACY_LEAGUE_TELEMETRY_INVALID')
        details = dict(status=row['status'], elapsed_ms=row['elapsed_ms'])
        if row['status']=='READ':
            matched, eligible = row['matched'], row['eligible']
            if type(matched) is not int or type(eligible) is not int or not 0 <= eligible <= matched:
                raise ValueError('ACCURACY_FIXTURE_TOTALS_INVALID')
            details.update(matched=matched, eligible=eligible)
        else:
            details['error'] = sanitized_error(row['error'])
        leagues[league] = details
    optional = {}
    for name in ('candidate','iddaa'):
        row = record['report']['optional'][name]
        if row['status'] not in ('RENDERED','FAILED','UNAVAILABLE'):
            raise ValueError('ACCURACY_OPTIONAL_STATUS_INVALID')
        optional[name] = dict(status=row['status'])
        if row['status']=='FAILED':
            optional[name]['error'] = sanitized_error(row['error'])
    rendered = sum(v['status']=='READ' for v in leagues.values())
    result = dict(status='UNCONFIRMED', release_sha=record['release_sha'] if type(record['release_sha']) is str and re.fullmatch(
                  r'[0-9a-f]{40}',record['release_sha']) else None, expected_parts=expected,
                  returned_parts=len(parts), verified_parts=0,leagues=leagues,optional=optional,
                  report_status='THREE_LEAGUES_READ' if rendered==3 else 'PARTIAL_REPORT' if rendered else 'NO_ARCHIVE_READ')
    if expected_release is None or record['release_sha'] != expected_release:
        result['status'] = 'RELEASE_UNCONFIRMED'
        return result
    if (not command or command['command'].lower() != '/accuracy'
            or command['request_sha256'] != record['request_sha256']
            or command['chat_id'] != record['chat_id'] or command['update_id'] != record['update_id']
            or not 0 < command['received_at_utc'] <= record['prepared_at_utc'] <= record['completed_at_utc'] <= now):
        return result
    if type(expected) is not int or not 0 < expected <= 100 or len(parts) > expected:
        return result
    message_ids = {p['message_id'] for p in parts}
    if len(message_ids) != len(parts):
        return result
    by_id = {p['message_id']: p['request_text_sha256'] for p in parts}
    bound = [e for e in acknowledgments if e and e['update_id'] == record['update_id']
             and e['bot_id'] == command['bot_id'] and e['chat_id'] == record['chat_id']
             and e['telegram_message_id'] in by_id
             and e['request_text_sha256'] == e['message_sha256'] == by_id[e['telegram_message_id']]
             and record['prepared_at_utc'] <= e['ack_at_utc'] <= record['completed_at_utc']]
    verified = evidence_report([command, *bound], asof_utc=now)['api_verified_messages']
    result['verified_parts'] = verified
    if verified == expected == len(parts) and record['send_status'] == 'ALL_PARTS_RETURNED':
        result['status'] = 'LOCAL_OFFICIAL_API_RECEIPTS_VERIFIED'
    return result


def read_accuracy(journal, update_id):
    if update_id is None:
        return inspect_accuracy(None, None, (), expected_release=None, now=0)
    record = journal.get(accuracy_key(update_id))
    if record is None:
        return dict(status='JOURNAL_ENTRY_UNAVAILABLE')
    command = journal.get(f'received:{update_id}')
    acknowledgments = [journal.get(digest(dict(chat=record['chat_id'], message=p['message_id'])))
                       for p in record['parts'][:100]]
    return inspect_accuracy(record, command, acknowledgments, expected_release=release_sha(), now=int(time.time()))
