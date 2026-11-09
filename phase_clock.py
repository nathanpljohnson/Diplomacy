"""Durable phase deadlines delivered by QStash; no process-local sleeping."""
import math
import os
from qstash import QStash, Receiver

DEFAULT_DURATIONS = {'opening': 1200, 'movement': 900, 'retreat': 180, 'adjustment': 300}


def suggested_seconds(phase, durations=None):
    durations = durations or DEFAULT_DURATIONS
    if phase.endswith('R'):
        return durations['retreat']
    if phase.endswith('A'):
        return durations['adjustment']
    return durations['opening'] if phase[1:5] == '1901' else durations['movement']


def configured():
    return all(os.getenv(key) for key in ('QSTASH_TOKEN', 'QSTASH_CURRENT_SIGNING_KEY', 'QSTASH_NEXT_SIGNING_KEY'))


def callback_url():
    return os.getenv('APP_URL', 'https://entente-diplomacy.vercel.app').rstrip('/') + '/api/timer-callback'


def publish(game_id, token, phase, deadline, now):
    if not configured():
        raise RuntimeError('The timer scheduler is not connected yet.')
    QStash(os.environ['QSTASH_TOKEN'], base_url=os.getenv('QSTASH_URL') or None).message.publish_json(
        url=callback_url(), body={'game_id': game_id, 'token': token, 'phase': phase},
        delay=f'{max(1, math.ceil(deadline - now))}s', retries=3)


def verify(signature, body):
    if not configured() or not signature:
        return False
    try:
        Receiver(current_signing_key=os.environ['QSTASH_CURRENT_SIGNING_KEY'],
                 next_signing_key=os.environ['QSTASH_NEXT_SIGNING_KEY']).verify(
                     signature=signature, body=body, url=callback_url())
        return True
    except Exception:
        return False
