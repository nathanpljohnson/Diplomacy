import json
import pytest
from diplomacy import Game
from app import create_app, map_schema


@pytest.fixture
def app(tmp_path):
    return create_app('sqlite:///' + str(tmp_path / 'test.db'))


def account(app, name):
    client = app.test_client()
    response = client.post('/api/register', json={'name':name, 'password':'a long secret passphrase'})
    assert response.status_code == 200, response.json
    return client, {'X-CSRF-Token': response.json['csrf']}


def make_game(client, headers, sandbox=False):
    response = client.post('/api/games', json={'title':'An evening accord','power':'FRANCE','sandbox':sandbox}, headers=headers)
    assert response.status_code == 201
    return response.json['id']


def test_classic_geography():
    data = map_schema()
    assert len(data['regions']) == 75
    assert sum(r['terrain'] == 'WATER' for r in data['regions']) == 19
    assert sum(r['terrain'] != 'WATER' for r in data['regions']) == 56
    assert len(data['supply_centers']) == 34
    assert sum(len(v) for v in data['homes'].values()) == 22
    assert len(set(data['supply_centers']) - {s for homes in data['homes'].values() for s in homes}) == 12
    assert {p:len(units) for p,units in data['starting_units'].items()} == {'AUSTRIA':3,'ENGLAND':3,'FRANCE':3,'GERMANY':3,'ITALY':3,'RUSSIA':4,'TURKEY':3}
    assert 'F STP/SC' in data['starting_units']['RUSSIA']
    assert {r['id'] for r in data['regions']} >= {'PAR','LON','MOS'}


def test_auth_csrf_and_logout(app):
    client, headers = account(app, 'host')
    assert client.post('/api/games', json={}).status_code == 403
    assert client.post('/api/games', json={}, headers={**headers,'Origin':'https://evil.example'}).status_code == 403
    assert client.get('/api/me').json['user']['name'] == 'host'
    assert client.post('/api/logout', json={}, headers=headers).status_code == 200
    assert client.get('/api/games').status_code == 401
    assert client.post('/api/login', json={'name':'host','password':'a long secret passphrase'}).status_code == 200


def test_private_orders_and_host_authority(app):
    host, hh = account(app, 'host')
    friend, fh = account(app, 'friend')
    stranger, sh = account(app, 'stranger')
    gid = make_game(host, hh)
    game = host.get(f'/api/games/{gid}').json
    assert friend.get(f'/api/games/{gid}').status_code == 403
    assert friend.post('/api/join', json={'code':game['invite'],'power':'ENGLAND'}, headers=fh).status_code == 200
    submitted = host.put(f'/api/games/{gid}/orders',json={'phase':'S1901M','power':'FRANCE','orders':['A PAR - BUR'],'ready':True},headers=hh)
    assert submitted.status_code == 200
    visible = friend.get(f'/api/games/{gid}').json
    assert visible['ready']['FRANCE'] is True
    assert 'FRANCE' not in visible['orders']
    assert visible['invite'] is None
    assert 'A PAR - BUR' not in friend.get(f'/api/games/{gid}/export').text
    assert friend.put(f'/api/games/{gid}/orders',json={'phase':'S1901M','power':'FRANCE','orders':[]},headers=fh).status_code == 403
    assert friend.post(f'/api/games/{gid}/adjudicate',json={'phase':'S1901M'},headers=fh).status_code == 403
    assert stranger.get(f'/api/games/{gid}/map').status_code == 403
    assert stranger.get(f'/api/games/{gid}/export').status_code == 403


def test_resolve_once_and_archive(app):
    host, headers = account(app, 'host')
    gid = make_game(host, headers, True)
    assert host.put(f'/api/games/{gid}/orders',json={'phase':'S1901M','power':'FRANCE','orders':['A PAR - BUR'],'ready':True},headers=headers).status_code == 200
    game = host.get(f'/api/games/{gid}').json
    payload = {'phase':game['phase'],'revision':game['revision'],'force':True}
    response = host.post(f'/api/games/{gid}/adjudicate',json=payload,headers=headers)
    assert response.status_code == 200, response.json
    assert response.json['phase'] == 'F1901M'
    assert host.post(f'/api/games/{gid}/adjudicate',json=payload,headers=headers).status_code == 409
    after = host.get(f'/api/games/{gid}').json
    assert 'A BUR' in after['state']['units']['FRANCE']
    assert after['orders']['FRANCE'] == []
    assert after['history'][0]['orders']['FRANCE'] == ['A PAR - BUR']
    assert host.get(f'/api/games/{gid}/map?phase=S1901M').status_code == 200
    assert host.get(f'/api/games/{gid}/export').json['history'][0]['name'] == 'S1901M'


def test_invalid_duplicate_and_stale_orders(app):
    client, headers = account(app, 'host')
    gid = make_game(client, headers)
    base = {'phase':'S1901M','power':'FRANCE','ready':True}
    for orders in [['A PAR - MOS'], ['A PAR H','A PAR - BUR'], [123]]:
        assert client.put(f'/api/games/{gid}/orders',json={**base,'orders':orders},headers=headers).status_code == 400
    assert client.put(f'/api/games/{gid}/orders',json={**base,'phase':'F1901M','orders':[]},headers=headers).status_code == 409


def test_ready_gate_and_seat_uniqueness(app):
    host, hh = account(app, 'host')
    friend, fh = account(app, 'friend')
    gid = make_game(host, hh)
    game = host.get(f'/api/games/{gid}').json
    assert friend.post('/api/join',json={'code':game['invite'],'power':'FRANCE'},headers=fh).status_code == 409
    assert friend.post('/api/join',json={'code':game['invite'],'power':'GERMANY'},headers=fh).status_code == 200
    assert friend.post('/api/join',json={'code':game['invite'],'power':'ITALY'},headers=fh).status_code == 409
    game = host.get(f'/api/games/{gid}').json
    assert host.post(f'/api/games/{gid}/adjudicate',json={'phase':game['phase'],'revision':game['revision']},headers=hh).status_code == 409


def test_retreats_builds_and_coasts(app):
    client, headers = account(app, 'host')
    gid = make_game(client, headers, True)
    # Simulate a legal engine position with a dislodgement, then verify the API preserves it.
    from sqlalchemy import text
    engine = Game()
    engine.clear_units()
    engine.set_units('FRANCE', ['A BUR','A GAS'])
    engine.set_units('GERMANY', ['A PAR'])
    engine.set_orders('FRANCE', ['A BUR - PAR','A GAS S A BUR - PAR'])
    engine.set_orders('GERMANY', ['A PAR H'])
    engine.process()
    assert engine.get_current_phase() == 'S1901R'
    with app.extensions['db'].begin() as conn:
        doc = json.loads(conn.execute(text('SELECT document FROM games WHERE id=:id'),{'id':gid}).scalar_one())
        doc['engine'] = engine.to_dict()
        conn.execute(text('UPDATE games SET document=:doc WHERE id=:id'),{'id':gid,'doc':json.dumps(doc)})
    game = client.get(f'/api/games/{gid}').json
    legal = [o for orders in game['possible'].values() for o in orders if ' R ' in o]
    assert legal
    assert client.put(f'/api/games/{gid}/orders',json={'phase':'S1901R','power':'GERMANY','orders':[legal[0]],'ready':True},headers=headers).status_code == 200
    game = client.get(f'/api/games/{gid}').json
    assert client.post(f'/api/games/{gid}/adjudicate',json={'phase':game['phase'],'revision':game['revision'],'force':True},headers=headers).status_code == 200


def test_source_download_excludes_private_data(app):
    import io, zipfile
    archive = zipfile.ZipFile(io.BytesIO(app.test_client().get('/source.zip').data))
    assert 'app.py' in archive.namelist()
    assert 'LICENSE' in archive.namelist()
    assert not any(name.startswith('data/') or '.env' == name or '__pycache__' in name for name in archive.namelist())


def test_preview_does_not_submit_or_leak(app):
    client, headers = account(app, 'host')
    gid = make_game(client, headers)
    response = client.post(f'/api/games/{gid}/preview', json={'phase':'S1901M','power':'FRANCE','orders':['A PAR - BUR']}, headers=headers)
    assert response.status_code == 200
    assert response.mimetype == 'image/svg+xml'
    after = client.get(f'/api/games/{gid}').json
    assert after['orders']['FRANCE'] == []
    assert after['ready']['FRANCE'] is False
    assert after['revision'] == 0
    assert client.post(f'/api/games/{gid}/preview',json={'phase':'S1901M','power':'GERMANY','orders':[]},headers=headers).status_code == 403


def test_adjustments_coasts_and_dbn_export(app):
    from sqlalchemy import text
    client, headers = account(app, 'host')
    gid = make_game(client, headers, True)
    engine = Game()
    engine.set_current_phase('W1901A')
    engine.set_units('RUSSIA', ['A MOS','A WAR','F SEV'], reset=True)
    with app.extensions['db'].begin() as conn:
        doc = json.loads(conn.execute(text('SELECT document FROM games WHERE id=:id'),{'id':gid}).scalar_one())
        doc['engine'] = engine.to_dict()
        conn.execute(text('UPDATE games SET document=:doc WHERE id=:id'),{'id':gid,'doc':json.dumps(doc)})
    game = client.get(f'/api/games/{gid}').json
    assert 'RUSSIA' in game['required']
    assert 'F STP/SC B' in game['possible']['STP']
    assert 'F STP/NC B' in game['possible']['STP']
    base = {'phase':'W1901A','power':'RUSSIA','ready':True}
    assert client.put(f'/api/games/{gid}/orders',json={**base,'orders':['F STP/SC B']},headers=headers).status_code == 200
    game = client.get(f'/api/games/{gid}').json
    assert client.post(f'/api/games/{gid}/adjudicate',json={'phase':game['phase'],'revision':game['revision'],'force':True},headers=headers).status_code == 200
    after = client.get(f'/api/games/{gid}').json
    assert 'F STP/SC' in after['state']['units']['RUSSIA']
    wire = client.get(f'/api/games/{gid}/export/dbn').json
    assert wire['GamePhases'][0]['Phase'] == 19013
    assert wire['GamePhases'][0]['Orders']['Russia'][0] == ['Stp',['b',['F',['Stp','sc']]],'s']
    assert ['F',['Stp','sc']] in wire['GamePhases'][-1]['Units']['Russia']


@pytest.mark.parametrize('units,orders,expected,absent', [
    ({'FRANCE':['A PAR','A MAR'],'GERMANY':['A MUN']},
     {'FRANCE':['A PAR - BUR','A MAR S A PAR - BUR'],'GERMANY':['A MUN - BUR']},
     {'FRANCE':['A BUR','A MAR'],'GERMANY':['A MUN']}, []),
    ({'FRANCE':['A PAR','A GAS'],'GERMANY':['A MUN'],'ITALY':['A SPA']},
     {'FRANCE':['A PAR - BUR','A GAS S A PAR - BUR'],'GERMANY':['A MUN - BUR'],'ITALY':['A SPA - GAS']},
     {'FRANCE':['A PAR','A GAS'],'GERMANY':['A MUN'],'ITALY':['A SPA']}, ['A BUR']),
    ({'ENGLAND':['A LON','F NTH']},
     {'ENGLAND':['A LON - BEL VIA','F NTH C A LON - BEL']},
     {'ENGLAND':['A BEL','F NTH']}, ['A LON']),
    ({'ENGLAND':['A LON','F NTH'],'FRANCE':['F ENG'],'GERMANY':['F HEL']},
     {'ENGLAND':['A LON - BEL VIA','F NTH C A LON - BEL'],'FRANCE':['F ENG - NTH'],'GERMANY':['F HEL S F ENG - NTH']},
     {'ENGLAND':['A LON'],'FRANCE':['F NTH']}, ['A BEL']),
])
def test_order_types_through_application(app, units, orders, expected, absent):
    """Exercise generated legal choices, submission, serialization and adjudication together."""
    from sqlalchemy import text
    client, headers = account(app, 'scenario_host')
    gid = make_game(client, headers, True)
    engine = Game()
    engine.clear_units()
    for power, values in units.items():
        engine.set_units(power, values)
    with app.extensions['db'].begin() as conn:
        doc = json.loads(conn.execute(text('SELECT document FROM games WHERE id=:id'),{'id':gid}).scalar_one())
        doc['engine'] = engine.to_dict()
        conn.execute(text('UPDATE games SET document=:doc WHERE id=:id'),{'id':gid,'doc':json.dumps(doc)})
    choices = client.get(f'/api/games/{gid}').json['possible']
    for power, values in orders.items():
        for order in values:
            assert order in choices[order.split()[1][:3]]
        response = client.put(f'/api/games/{gid}/orders',json={'phase':'S1901M','power':power,'orders':values,'ready':True},headers=headers)
        assert response.status_code == 200, response.json
    game = client.get(f'/api/games/{gid}').json
    response = client.post(f'/api/games/{gid}/adjudicate',json={'phase':game['phase'],'revision':game['revision'],'force':True},headers=headers)
    assert response.status_code == 200
    state = client.get(f'/api/games/{gid}').json['state']
    for power, values in expected.items():
        for unit in values:
            assert unit in state['units'][power]
    all_units = [u for values in state['units'].values() for u in values]
    for unit in absent:
        assert unit not in all_units


def test_game_list_shows_actual_phase(app):
    client,headers=account(app,'phaselist')
    gid=make_game(client,headers)
    listed=next(row for row in client.get('/api/games').json['games'] if row['id']==gid)
    assert listed['phase']==client.get(f'/api/games/{gid}').json['phase']=='S1901M'


def test_revision_cache_reduces_reads_and_observes_external_changes(app):
    from sqlalchemy import event, text
    host, headers = account(app, 'cachehost')
    gid = make_game(host, headers, True)
    full_reads = []
    def record(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith('SELECT games.document'):
            full_reads.append(statement)
    engine = app.extensions['db']
    event.listen(engine, 'before_cursor_execute', record)
    first = host.get(f'/api/games/{gid}')
    assert first.status_code == 200
    reads = len(full_reads)
    for _ in range(3):
        response = host.get(f'/api/games/{gid}')
        assert response.status_code == 200
        assert response.json['revision'] == first.json['revision']
    assert len(full_reads) == reads
    # Simulate another server instance writing a new revision.
    with engine.begin() as conn:
        raw = conn.execute(text('SELECT document FROM games WHERE id=:id'), {'id':gid}).scalar_one()
        doc = json.loads(raw)
        doc['title'] = 'Updated by another instance'
        conn.execute(text('UPDATE games SET document=:doc, revision=revision+1 WHERE id=:id'), {'doc':json.dumps(doc),'id':gid})
    fresh = host.get(f'/api/games/{gid}')
    assert fresh.json['title'] == 'Updated by another instance'
    assert len(full_reads) == reads + 1
    event.remove(engine, 'before_cursor_execute', record)
