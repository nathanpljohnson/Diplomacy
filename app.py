"""Entente — private, host-paced Diplomacy. AGPL-3.0-or-later."""
import hashlib
from functools import lru_cache
import io
import json
import os
from pathlib import Path
import re
import secrets
import time
import zipfile
import math
import phase_clock
import drunk_power
from order_art import draw_orders, ANCHORS
from country_art import country_borders

from diplomacy import Game
from diplomacy.engine.renderer import Renderer
from flask import Flask, g, jsonify, request, send_file, send_from_directory
from sqlalchemy import Column, Integer, MetaData, String, Table, Text, create_engine, select, update, delete, func, literal_column
from sqlalchemy.exc import IntegrityError
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash, generate_password_hash

ROOT = Path(__file__).parent
POWERS = ['AUSTRIA', 'ENGLAND', 'FRANCE', 'GERMANY', 'ITALY', 'RUSSIA', 'TURKEY']
COLORS = dict(zip(POWERS, ['#c85c4e','#8c5ab5','#3d85b5','#85542e','#548c4c','#57545f','#d77726']))
TERRITORY_COLORS = dict(zip(POWERS, ['#e9c7be','#dbcbe8','#c2dcea','#c8ab8c','#cdddbe','#c9c5cf','#f1c79f']))
UNIT_EDGES = dict(zip(POWERS, ['#702d28','#49305f','#23485f','#432713','#2d4b29','#292630','#713a16']))
STARTING_TERRITORY = {
    'AUSTRIA':'BOH BUD GAL TRI TYR VIE', 'ENGLAND':'CLY EDI LON LVP WAL YOR',
    'FRANCE':'BRE BUR GAS MAR PAR PIC', 'GERMANY':'BER KIE MUN PRU RUH SIL',
    'ITALY':'APU NAP PIE ROM TUS VEN', 'RUSSIA':'FIN LVN MOS SEV STP UKR WAR',
    'TURKEY':'ANK ARM CON SMY SYR'}
SVG_ALIASES = {'NAT':'NAO','NRG':'NWG','MID':'MAO','GOL':'LYO','TYN':'TYS'}


def create_app(database_url=None):
    app = Flask(__name__, static_folder='public/static', static_url_path='/static')
    app.config['MAX_CONTENT_LENGTH'] = 100_000
    url = database_url or os.getenv('DATABASE_URL')
    if not url:
        if os.getenv('VERCEL'):
            raise RuntimeError('Set DATABASE_URL to persistent PostgreSQL before deploying.')
        (ROOT / 'data').mkdir(exist_ok=True)
        url = 'sqlite:///' + str(ROOT / 'data/entente.db')
    if url.startswith(('postgres://', 'postgresql://')):
        url = 'postgresql+psycopg://' + url.split('://', 1)[1]
    db = create_engine(url, pool_pre_ping=True, **({'connect_args': {'timeout': 20}} if url.startswith('sqlite') else {}))
    metadata = MetaData()
    users = Table('users', metadata, Column('id', String, primary_key=True), Column('name', String, unique=True), Column('password', Text))
    sessions = Table('sessions', metadata, Column('token', String, primary_key=True), Column('user_id', String), Column('csrf', String), Column('expires', Integer))
    games = Table('games', metadata, Column('id', String, primary_key=True), Column('host', String), Column('revision', Integer), Column('document', Text))
    attempts = Table('attempts', metadata, Column('key', String, primary_key=True), Column('count', Integer))
    metadata.create_all(db)
    app.extensions['db'] = db

    def fail(message, status=400):
        response = jsonify(error=message)
        response.status_code = status
        return response

    @app.errorhandler(HTTPException)
    def http_error(error):
        return fail(error.description, error.code)

    @app.before_request
    def authenticate():
        g.user = None
        g.csrf = None
        token = request.cookies.get('entente_session', '')
        if token:
            with db.connect() as conn:
                row = conn.execute(select(users.c.id, users.c.name, sessions.c.csrf).join(sessions, users.c.id == sessions.c.user_id).where(sessions.c.token == hashlib.sha256(token.encode()).hexdigest(), sessions.c.expires > int(time.time()))).mappings().first()
                if row:
                    g.user = {'id': row['id'], 'name': row['name']}
                    g.csrf = row['csrf']
        if request.method in ('POST', 'PUT', 'DELETE'):
            if request.headers.get('Origin') and request.headers['Origin'] != request.host_url.rstrip('/'):
                return fail('This request must come from this site.', 403)
            if request.path not in ('/api/login', '/api/register', '/api/timer-callback'):
                if not g.user:
                    return fail('Sign in to continue.', 401)
                if not secrets.compare_digest(request.headers.get('X-CSRF-Token', ''), g.csrf):
                    return fail('Your session changed. Refresh and try again.', 403)

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if request.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    def body():
        value = request.get_json(silent=True)
        if not isinstance(value, dict):
            from flask import abort
            abort(400, 'Expected a JSON object.')
        return value

    def rate_limit(name):
        # Database-backed throttle works across serverless instances. No raw IPs retained.
        for key, limit in [(request.remote_addr or '', 40), ((request.remote_addr or '') + name, 10)]:
            digest = hashlib.sha256((str(int(time.time()) // 900) + key).encode()).hexdigest()
            with db.begin() as conn:
                conn.exec_driver_sql('INSERT INTO attempts (key, count) VALUES (%s, 1) ON CONFLICT (key) DO UPDATE SET count = attempts.count + 1' if db.dialect.name == 'postgresql' else 'INSERT INTO attempts (key, count) VALUES (?, 1) ON CONFLICT (key) DO UPDATE SET count = attempts.count + 1', (digest,))
                count = conn.execute(select(attempts.c.count).where(attempts.c.key == digest)).scalar_one()
            if count > limit:
                return False
        return True

    @app.get('/api/me')
    def me():
        return jsonify(user=g.user, csrf=g.csrf)

    @app.post('/api/register')
    @app.post('/api/login')
    def login():
        data = body()
        name, password = str(data.get('name', '')).strip().lower(), str(data.get('password', ''))
        if not rate_limit(name):
            return fail('Too many attempts. Try again in 15 minutes.', 429)
        if not re.fullmatch(r'[a-z0-9_-]{3,24}', name) or not 12 <= len(password) <= 128:
            return fail('Use a 3–24 character username (letters, numbers, _ or -) and a 12–128 character password.')
        with db.begin() as conn:
            if request.path.endswith('register'):
                try:
                    conn.execute(users.insert().values(id=secrets.token_hex(16), name=name, password=generate_password_hash(password)))
                except IntegrityError:
                    return fail('That username is taken. Choose another.', 409)
            row = conn.execute(select(users).where(users.c.name == name)).mappings().first()
            if not check_password_hash(row['password'] if row else DUMMY_HASH, password) or not row:
                return fail('Username or password is incorrect.', 401)
            token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
            conn.execute(delete(sessions).where(sessions.c.expires < int(time.time())))
            conn.execute(sessions.insert().values(token=hashlib.sha256(token.encode()).hexdigest(), user_id=row['id'], csrf=csrf, expires=int(time.time()) + 86400 * 14))
        response = jsonify(user={'id': row['id'], 'name': name}, csrf=csrf)
        response.set_cookie('entente_session', token, httponly=True, secure=bool(os.getenv('VERCEL')) or request.is_secure, samesite='Strict', max_age=86400 * 14)
        return response

    @app.post('/api/logout')
    def logout():
        with db.begin() as conn:
            conn.execute(delete(sessions).where(sessions.c.token == hashlib.sha256(request.cookies.get('entente_session', '').encode()).hexdigest()))
        response = jsonify(ok=True)
        response.delete_cookie('entente_session')
        return response

    @lru_cache(maxsize=128)
    def document_at_revision(game_id, revision):
        # Cache only immutable serialized snapshots. Every request still checks
        # the database revision, and authorization is checked by load().
        with db.connect() as conn:
            return conn.execute(select(games.c.document).where(
                games.c.id == game_id, games.c.revision == revision)).scalar_one_or_none()

    def read_record(game_id):
        from flask import abort
        for _ in range(4):
            with db.connect() as conn:
                row = conn.execute(select(games.c.id, games.c.host, games.c.revision)
                    .where(games.c.id == game_id)).mappings().first()
            if not row:
                abort(404, 'Game not found.')
            document = document_at_revision(game_id, row['revision'])
            if document is not None:
                row = dict(row, document=document)
                doc = json.loads(document)
                return row, doc, Game.from_dict(doc['engine'])
        abort(409, 'The game changed. Refresh and try again.')

    def load(game_id):
        from flask import abort
        if not g.user:
            abort(401, 'Sign in to continue.')
        row, doc, game = read_record(game_id)
        if g.user['id'] != row['host'] and g.user['id'] not in [s['id'] for s in doc['seats'].values()]:
            abort(403, 'Join this game using its invitation code first.')
        return settle_due(game_id)

    def commit(row, doc):
        from flask import abort
        with db.begin() as conn:
            result = conn.execute(update(games).where(games.c.id == row['id'], games.c.revision == row['revision']).values(document=json.dumps(doc), revision=row['revision'] + 1))
            if result.rowcount != 1:
                abort(409, 'The game changed. Refresh and try again; your action was not applied.')

    def now():
        return int(time.time())

    def arm(row, doc, game):
        timer = doc.get('timer')
        if not timer or not timer.get('enabled'):
            return
        timer['token'] = secrets.token_urlsafe(24)
        timer['remaining'] = phase_clock.suggested_seconds(game.get_current_phase(), timer['durations']) if not game.is_game_done else 0
        timer['error'] = None
        if game.is_game_done:
            timer.update(enabled=False, paused=True, deadline=None)
        elif timer.get('paused'):
            timer['deadline'] = None
        else:
            timer['deadline'] = now() + timer['remaining']
            try:
                phase_clock.publish(row['id'], timer['token'], game.get_current_phase(), timer['deadline'], now())
            except Exception:
                # Resolve the phase safely, then stop the clock if its next wake-up cannot be scheduled.
                timer.update(paused=True, deadline=None, error='The next deadline could not be scheduled. The host can resume the clock to retry.')

    def resolve_document(row, doc, game, automatic=False):
        surviving = [p for p in POWERS if (game.powers[p].units or game.powers[p].centers) and p != doc.get('drunk_power')]
        drunk_result = drunk_power.choose_orders(doc, game)
        draws = [p for p in surviving if doc['submissions'].get(p, {}).get('draw')]
        if surviving and set(draws) == set(surviving):
            drunk_result = None
            result, _ = game.draw(winners=[p for p in POWERS if game.powers[p].units or game.powers[p].centers])
            doc['ended_reason'] = 'draw'
        else:
            for power in POWERS:
                sheet = doc['submissions'].get(power, {})
                orders = drunk_result['orders'] if drunk_result and power == drunk_result['power'] else [] if sheet.get('draw') else sheet.get('orders', [])
                game.set_orders(power, orders)
            result = game.process()
        doc['history'].append(dict(name=result.name, state=result.state, orders=result.orders,
            results={loc: [str(item) for item in items if str(item)] for loc, items in result.results.items()},
            draw_offers=draws, automatic=automatic, drunk_selection=drunk_result))
        doc['engine'] = game.to_dict()
        doc['submissions'] = {}
        doc['drunk_submissions'] = {}
        arm(row, doc, game)

    def settle_due(game_id, expected_token=None):
        from flask import abort
        for _ in range(4):
            row, doc, game = read_record(game_id)
            timer = doc.get('timer', {})
            if expected_token and timer.get('token') != expected_token:
                return row, doc, game
            if game.is_game_done or not timer.get('enabled') or timer.get('paused') or not timer.get('deadline') or timer['deadline'] > now():
                return row, doc, game
            resolve_document(row, doc, game, automatic=True)
            with db.begin() as conn:
                changed = conn.execute(update(games).where(games.c.id == game_id, games.c.revision == row['revision'])
                    .values(document=json.dumps(doc), revision=row['revision'] + 1))
            if changed.rowcount == 1:
                row['revision'] += 1
                return row, doc, game
        abort(409, 'The game is busy settling its deadline. Refresh in a moment.')

    def mine(row, doc):
        return POWERS if doc['sandbox'] and row['host'] == g.user['id'] else [p for p, seat in doc['seats'].items() if seat['id'] == g.user['id']]

    def editable(row, doc, game):
        own = mine(row, doc)
        power = doc.get('drunk_power')
        return own + ([power] if own and power and power not in own and game.phase_type == 'M' else [])

    def sheet_for(doc, power):
        return doc.get('drunk_submissions', {}).get(g.user['id'], {}) if power == doc.get('drunk_power') else doc['submissions'].get(power, {})

    def view(row, doc, game):
        controlled = editable(row, doc, game)
        possible = game.get_all_possible_orders()
        orderable = game.get_orderable_locations()
        result = dict(id=row['id'], title=doc['title'], revision=row['revision'], host=row['host'] == g.user['id'], sandbox=doc['sandbox'], seats=doc['seats'], powers=POWERS, controlled=controlled, phase=game.get_current_phase(), phase_label=game.phase, state=game.get_state(), completed=game.is_game_done, outcome=game.outcome, required=[p for p in POWERS if orderable[p] and p != doc.get('drunk_power')], ready={p: bool(doc['submissions'].get(p, {}).get('ready')) for p in POWERS}, orders={p: sheet_for(doc,p).get('orders', []) for p in controlled}, orderable={p: orderable[p] for p in controlled}, possible={loc: possible.get(loc, []) for p in controlled for loc in orderable[p]}, history=[{'phase': h['name'], 'results': h['results'], 'orders': h['orders'], 'draw_offers':h.get('draw_offers',[]), 'automatic':h.get('automatic',False), 'drunk_selection':h.get('drunk_selection')} for h in doc['history']], invite=doc['invite'] if row['host'] == g.user['id'] and not doc['sandbox'] else None)
        if doc.get('drunk_power') in controlled:
            result['ready'][doc['drunk_power']] = bool(sheet_for(doc,doc['drunk_power']).get('ready'))
        result.update(drunk_power=doc.get('drunk_power'), drunk_players=drunk_power.players(doc) if doc.get('drunk_power') else [], draws={p:bool(doc['submissions'].get(p,{}).get('draw')) for p in controlled},
            ended_reason=doc.get('ended_reason'), source=doc.get('source'), server_time=now(),
            timer={key:value for key,value in doc.get('timer',{}).items() if key!='token'},
            timer_available=phase_clock.configured(), suggested_durations=phase_clock.DEFAULT_DURATIONS)
        result['retreat_options']={}
        if game.phase_type=='R':
            for power in controlled:
                displaced=[]
                for unit in game.get_state()['retreats'][power]:
                    legal=sorted({o for loc in orderable[power] for o in possible.get(loc,[]) if o.startswith(unit+' ') and o.split()[2] in ('R','D')},key=lambda o:(o.split()[2]=='D',o))
                    displaced.append(dict(unit=unit,province=unit.split()[1],orders=legal))
                result['retreat_options'][power]=displaced
        result['construction']={}
        if game.phase_type=='A':
            occupied={unit.split()[-1][:3] for power in game.powers.values() for unit in power.units}
            for power in controlled:
                p=game.powers[power]
                count=game.get_state()['builds'][power]['count']
                choices=[]
                for center in sorted(p.centers):
                    legal=sorted({order for loc in orderable[power] for order in possible.get(loc,[]) if len(order.split())==3 and order.endswith(' B') and order.split()[1][:3]==center})
                    choices.append(dict(province=center,home=center in p.homes,occupied=center in occupied,orders=legal))
                removals=sorted({order for loc in orderable[power] for order in possible.get(loc,[]) if order.endswith(' D')}) if count<0 else []
                result['construction'][power]=dict(count=count,potential=len(p.centers)-len(p.units),centers=choices,removals=removals)
        return result

    @app.get('/api/games')
    def list_games():
        if not g.user:
            return fail('Sign in to continue.', 401)
        output = []
        with db.connect() as conn:
            for row in conn.execute(select(games)).mappings():
                doc = json.loads(row['document'])
                if row['host'] == g.user['id'] or g.user['id'] in [s['id'] for s in doc['seats'].values()]:
                    output.append(dict(id=row['id'], title=doc['title'], phase=Game.from_dict(doc['engine']).get_current_phase(), sandbox=doc['sandbox'], seats=len(doc['seats'])))
        return jsonify(games=output[::-1])

    @app.post('/api/games')
    def create_game():
        data = body()
        title = str(data.get('title', '')).strip()
        power = data.get('power', 'FRANCE')
        if not 1 <= len(title) <= 80 or power not in POWERS:
            return fail('Enter a game name (up to 80 characters) and choose a power.')
        drunk = data.get('drunk_power') or None
        if drunk and (drunk not in POWERS or data.get('sandbox') is True or drunk == power and not data.get('host_only')):
            return fail('Choose an unclaimed drunk power for a multiplayer game.')
        game_id = secrets.token_urlsafe(12)
        sandbox = data.get('sandbox') is True
        doc = dict(drunk_power=drunk, drunk_submissions={}, title=title, sandbox=sandbox, seats={} if data.get('host_only') is True and not sandbox else {power:g.user}, engine=Game().to_dict(), submissions={}, history=[], invite=secrets.token_urlsafe(18))
        with db.begin() as conn:
            conn.execute(games.insert().values(id=game_id, host=g.user['id'], revision=0, document=json.dumps(doc)))
        return jsonify(id=game_id), 201

    @app.post('/api/join')
    def join():
        data = body()
        code, power = str(data.get('code', '')), data.get('power')
        with db.connect() as conn:
            rows = conn.execute(select(games)).mappings().all()
        for row in rows:
            doc = json.loads(row['document'])
            if not doc['sandbox'] and secrets.compare_digest(doc['invite'], code):
                if Game.from_dict(doc['engine']).is_game_done:
                    return fail('This game has ended.',409)
                if power not in POWERS or power in doc['seats'] or power == doc.get('drunk_power'):
                    return fail('That power is unavailable. Choose another.', 409)
                if g.user['id'] in [s['id'] for s in doc['seats'].values()]:
                    return fail('You already have a power in this game.', 409)
                doc['seats'][power] = g.user
                commit(row, doc)
                return jsonify(id=row['id'])
        return fail('Invitation code not found.', 404)

    @app.get('/api/games/<game_id>')
    def game_view(game_id):
        return jsonify(view(*load(game_id)))

    @app.put('/api/games/<game_id>/orders')
    def orders(game_id):
        row, doc, game = load(game_id)
        data = body()
        power = data.get('power')
        if data.get('phase') != game.get_current_phase() or game.is_game_done:
            return fail('This phase has ended. Refresh the board.', 409)
        if power not in editable(row, doc, game):
            return fail('You can only submit orders for your own power.', 403)
        orders = data.get('orders')
        if not isinstance(orders, list) or len(orders) > 50 or any(not isinstance(o, str) or len(o) > 100 for o in orders):
            return fail('Orders must be a list of valid order strings.')
        is_draw = data.get('draw') is True
        if is_draw and power == doc.get('drunk_power'):
            return fail('The drunk power cannot offer a draw. Offer it for your own country.')
        if is_draw and orders:
            return fail('Choose moves or a draw offer. They cannot be submitted together.')
        if is_draw and not (game.powers[power].units or game.powers[power].centers):
            return fail('An eliminated power cannot offer a draw.')
        possible = game.get_all_possible_orders()
        legal = {o for loc in game.get_orderable_locations()[power] for o in possible.get(loc, [])}
        if any(order not in legal for order in orders):
            return fail('An order is not legal in this position. Use the order builder, including the correct coast.')
        units = [o.split()[1][:3] for o in orders if o != 'WAIVE']
        if len(units) != len(set(units)):
            return fail('Submit only one order per province.')
        build_count = game.get_state()['builds'][power]['count']
        if game.phase_type == 'A' and len(orders) > abs(build_count):
            return fail('Too many adjustment orders for your supply center count.')
        sheet = {'orders': orders, 'ready': is_draw or data.get('ready') is True, 'draw':is_draw}
        # Independent player sheets can arrive together. Merge only this sheet
        # into the latest revision; never replay it into a later phase.
        for _ in range(12):
            if power == doc.get('drunk_power'):
                doc.setdefault('drunk_submissions', {})[g.user['id']] = sheet
            else:
                doc['submissions'][power] = sheet
            conditions = [games.c.id == game_id, games.c.revision == row['revision']]
            timer = doc.get('timer', {})
            if timer.get('enabled') and not timer.get('paused') and timer.get('deadline'):
                # Evaluate time inside the write, after request/network delays.
                clock = func.extract('epoch', func.clock_timestamp()) if db.dialect.name == 'postgresql' else literal_column("CAST(strftime('%s','now') AS INTEGER)")
                conditions.append(clock < timer['deadline'])
            with db.begin() as conn:
                changed = conn.execute(update(games).where(*conditions)
                    .values(document=json.dumps(doc), revision=row['revision'] + 1))
            if changed.rowcount == 1:
                return jsonify(ok=True)
            row, doc, game = load(game_id)
            if data.get('phase') != game.get_current_phase() or game.is_game_done:
                return fail('This phase has ended. Refresh the board.', 409)
            if power not in editable(row, doc, game):
                return fail('This power is no longer available to you.', 403)
        return fail('The game is busy saving orders. Please submit again.', 409)

    @app.post('/api/games/<game_id>/adjudicate')
    def adjudicate(game_id):
        row, doc, game = load(game_id)
        data = body()
        if row['host'] != g.user['id']:
            return fail('Only the host can adjudicate.', 403)
        if data.get('phase') != game.get_current_phase() or data.get('revision') != row['revision'] or game.is_game_done:
            return fail('The game changed. Refresh before adjudicating.', 409)
        needed = [p for p, locations in game.get_orderable_locations().items() if locations and p != doc.get('drunk_power')]
        missing = [p for p in needed if not doc['submissions'].get(p, {}).get('ready')]
        if missing and data.get('force') is not True:
            return jsonify(error='Some powers have not submitted. Confirm to resolve with default orders.', missing=missing), 409
        resolve_document(row, doc, game)
        commit(row, doc)
        return jsonify(ok=True, phase=game.get_current_phase())

    @app.put('/api/games/<game_id>/drunk-power')
    def configure_drunk(game_id):
        row, doc, game = load(game_id)
        if row['host'] != g.user['id']:
            return fail('Only the host can set the drunk power.', 403)
        power = body().get('power') or None
        if doc['sandbox'] or doc['history'] or doc.get('timer',{}).get('enabled'):
            return fail('Set the drunk power before the first adjudication and before starting the clock.', 409)
        if power and (power not in POWERS or power in doc['seats']):
            return fail('Choose an unclaimed country.', 409)
        doc['drunk_power'] = power
        doc['drunk_submissions'] = {}
        commit(row,doc)
        return jsonify(ok=True)

    @app.post('/api/games/<game_id>/timer')
    def timer_controls(game_id):
        row, doc, game = load(game_id)
        data = body()
        if row['host'] != g.user['id']:
            return fail('Only the host can change the clock.',403)
        if game.is_game_done or doc['sandbox']:
            return fail('Timers are available only in active multiplayer games.',409)
        if data.get('phase') and data['phase']!=game.get_current_phase():
            return fail('The phase changed. Refresh before changing its clock.',409)
        timer = doc.setdefault('timer',dict(enabled=False,paused=True,deadline=None,remaining=0,durations=dict(phase_clock.DEFAULT_DURATIONS)))
        action = data.get('action')
        if action == 'start':
            durations = data.get('durations',timer['durations'])
            if not isinstance(durations,dict) or set(durations)!=set(phase_clock.DEFAULT_DURATIONS) or any(type(v) is not int or not 60<=v<=86400 for v in durations.values()):
                return fail('Set each phase duration between 1 minute and 24 hours.')
            timer.update(enabled=True,paused=False,durations=durations)
            arm(row,doc,game)
            if timer.get('error'):
                return fail('The scheduler could not start the clock. No timer changes were saved. Try again.',503)
        elif action == 'pause' and timer.get('enabled'):
            if not timer.get('paused'):
                timer['remaining'] = max(0,timer['deadline']-now())
            timer.update(paused=True,deadline=None,token=secrets.token_urlsafe(24),error=None)
        elif action == 'resume' and timer.get('enabled') and timer.get('paused'):
            timer.update(paused=False,deadline=now()+max(1,timer['remaining']),token=secrets.token_urlsafe(24),error=None)
            try:
                phase_clock.publish(game_id,timer['token'],game.get_current_phase(),timer['deadline'],now())
            except Exception:
                return fail('The scheduler could not resume the clock. It remains paused.',503)
        elif action == 'stop':
            timer.update(enabled=False,paused=True,deadline=None,token=secrets.token_urlsafe(24),error=None)
        else:
            return fail('That clock action is not available.')
        commit(row,doc)
        return jsonify(ok=True)

    @app.post('/api/timer-callback')
    def timer_callback():
        if not phase_clock.verify(request.headers.get('Upstash-Signature',''),request.get_data(as_text=True)):
            return fail('Invalid scheduler signature.',401)
        data = body()
        if not isinstance(data.get('game_id'),str) or not isinstance(data.get('token'),str):
            return fail('Invalid deadline message.')
        row, doc, game = read_record(data['game_id'])
        timer=doc.get('timer',{})
        if timer.get('token')!=data['token'] or game.get_current_phase()!=data.get('phase') or game.is_game_done or timer.get('paused') or not timer.get('enabled'):
            return jsonify(ok=True,ignored=True)
        if timer.get('deadline',0)>now():
            return fail('This deadline is not due yet.',503)
        settle_due(data['game_id'],expected_token=data['token'])
        return jsonify(ok=True)

    @app.post('/api/games/<game_id>/scenarios')
    def create_scenario(game_id):
        row, doc, game = load(game_id)
        data = body()
        phase = data.get('phase',game.get_current_phase())
        historical=next((h for h in doc['history'] if h['name']==phase),None)
        if phase != game.get_current_phase() and not historical:
            return fail('That position is no longer available. Refresh the game.',409)
        state=json.loads(json.dumps(historical['state'] if historical else game.get_state()))
        if state['name']=='COMPLETED':
            state['name']=doc['history'][-1]['name'] if doc['history'] else 'S1901M'
        study=Game()
        study.set_state(state)
        study.clear_orders()
        own = historical['orders'] if historical else {p:sheet_for(doc,p).get('orders',[]) for p in editable(row,doc,game)}
        if not historical and data.get('draft') is not None:
            draft=data['draft']
            if not isinstance(draft,dict) or draft.get('power') not in editable(row,doc,game):
                return fail('You can only copy your own current draft.',403)
            draft_orders=draft.get('orders')
            possible=game.get_all_possible_orders()
            legal={o for loc in game.get_orderable_locations()[draft['power']] for o in possible.get(loc,[])}
            if not isinstance(draft_orders,list) or len(draft_orders)>50 or any(not isinstance(o,str) or o not in legal for o in draft_orders):
                return fail('That draft contains an invalid order.')
            own[draft['power']]=draft_orders
        study_id=secrets.token_urlsafe(12)
        study_doc=dict(title=(doc['title']+' · '+phase+' study')[:80],sandbox=True,seats={},engine=study.to_dict(),
            submissions={p:{'orders':orders,'ready':False} for p,orders in own.items()},history=[],invite=secrets.token_urlsafe(18),
            source={'game_id':game_id,'title':doc['title'],'phase':phase})
        with db.begin() as conn:
            conn.execute(games.insert().values(id=study_id,host=g.user['id'],revision=0,document=json.dumps(study_doc)))
        return jsonify(id=study_id),201

    @app.get('/api/games/<game_id>/map')
    def game_map(game_id):
        row, doc, game = load(game_id)
        phase = request.args.get('phase')
        overlay_orders=None;results=None
        if phase:
            historical = next((h for h in doc['history'] if h['name'] == phase), None)
            if not historical:return fail('Phase not found.', 404)
            game = Game();game.set_state(historical['state'])
            overlay_orders=historical['orders'];results=historical['results']
        elif request.args.get('results')=='1' and doc['history']:
            overlay_orders=doc['history'][-1]['orders'];results=doc['history'][-1]['results']
        else:
            for power in editable(row, doc, game):
                game.set_orders(power, sheet_for(doc,power).get('orders', []))
        return app.response_class(art_map(game,overlay_orders,results), mimetype='image/svg+xml')

    @app.get('/api/map')
    def demo_map():
        return app.response_class(art_map(Game()), mimetype='image/svg+xml')

    @app.post('/api/games/<game_id>/preview')
    def preview_orders(game_id):
        row, doc, game = load(game_id)
        data = body()
        power = data.get('power')
        if power not in editable(row, doc, game):
            return fail('You can only preview your own orders.', 403)
        if data.get('phase') != game.get_current_phase():
            return fail('The phase changed. Refresh the board.', 409)
        orders = data.get('orders')
        possible = game.get_all_possible_orders()
        legal = {o for loc in game.get_orderable_locations()[power] for o in possible.get(loc, [])}
        if not isinstance(orders, list) or len(orders) > 50 or any(not isinstance(o, str) or o not in legal for o in orders):
            return fail('Preview contains an invalid order.')
        for controlled in editable(row, doc, game):
            game.set_orders(controlled, orders if controlled == power else sheet_for(doc,controlled).get('orders', []))
        return app.response_class(art_map(game), mimetype='image/svg+xml')

    @app.get('/api/provinces')
    def provinces():
        return jsonify(map_schema())

    @app.get('/api/games/<game_id>/export')
    def export(game_id):
        row, doc, game = load(game_id)
        # Only resolved orders and public state are exported. Current private orders never leak.
        return jsonify(format='entente-1', map='standard', drunk_power=doc.get('drunk_power'), phase=game.get_current_phase(), state=game.get_state(), history=doc['history'])

    @app.get('/api/games/<game_id>/export/dbn')
    def export_dbn(game_id):
        row, doc, game = load(game_id)
        return jsonify(dbn_export(doc, game))

    @app.get('/source.zip')
    def source():
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in ROOT.rglob('*'):
                relative = path.relative_to(ROOT)
                if path.is_file() and not any((part.startswith('.') and part not in ('.gitignore', '.vercelignore', '.env.example')) or part in ('data', '__pycache__', 'node_modules') for part in relative.parts) and path.suffix not in ('.db', '.pyc', '.zip'):
                    archive.write(path, str(relative))
        stream.seek(0)
        return send_file(stream, download_name='entente-source.zip', as_attachment=True)

    @app.get('/')
    def index():
        return send_from_directory(app.static_folder, 'index.html')

    @app.get('/favicon.ico')
    def favicon():
        return send_from_directory(app.static_folder, 'favicon.svg', mimetype='image/svg+xml')

    @app.get('/rules')
    def rules():
        return send_from_directory(app.static_folder, 'rules.html')

    return app


def map_schema():
    game = Game()
    mp = game.map
    names = {code: name.title() for name, code in mp.loc_name.items()}
    regions = sorted({loc.upper() for loc in mp.locs if '/' not in loc and mp.area_type(loc) != 'SHUT'})
    return dict(format='entente-map-1', map='standard', start='S1901M', regions=[dict(id=loc, name=names.get(loc, loc), terrain=mp.area_type(loc), supply_center=loc in mp.scs, home_power=next((p for p in POWERS if loc in game.powers[p].homes),None), starting_owner=territory_owner(game,loc), coasts=[coast for coast in mp.find_coasts(loc) if '/' in coast], adjacent=mp.abut_list(loc)) for loc in regions], supply_centers=mp.scs, homes={p: game.powers[p].homes for p in POWERS}, starting_units={p: game.powers[p].units for p in POWERS})


def art_map(game, overlay_orders=None, results=None):
    """Adapt engine-rendered jDip SVG, retaining notices and exact province geometry."""
    labels_path=ROOT/'map_labels.json'
    labels=json.loads(labels_path.read_text()) if labels_path.exists() else {}
    if any('unit_center' in position for position in labels.values()):
        game.renderer=Renderer(game)
        for loc,position in labels.items():
            if 'unit_center' in position:
                x,y=position['unit_center']
                if loc in game.renderer.metadata['coord']:
                    game.renderer.metadata['coord'][loc]['unit']=(str(x-20),str(y-20))
    # Keep Bulgaria's fleet pieces on the same inland coast anchors as arrows.
    for loc in ('BUL/EC', 'BUL/SC'):
        x,y=ANCHORS[loc]['center']
        game.renderer.metadata['coord'][loc]['unit']=(str(x-20),str(y-20))
    svg = game.render(incl_orders=True, incl_abbrev=True)
    svg = svg[svg.index('<svg'):]
    style = '''
    svg {background:#c6d8d5} .water {fill:#c6d8d5;stroke:#748e8b;stroke-width:1.3}
    .nopower,.neutral {fill:#eeebe3;stroke:#716b58;stroke-width:1.4}
    .impassable {fill:#d1cfc7;stroke:#716b58}
    .labeltext24,.labeltext18 {fill:#203c34;stroke:none;font-family:Georgia,serif;font-style:normal;font-weight:600;font-size:19px}
    #CurrentNote,#CurrentNote2,#CurrentPhase,.currentnoterect {display:none}
    #MapLayer [id^="_"] {cursor:pointer;transition:filter .15s}
    #MapLayer [id^="_"]:hover {filter:brightness(1.12)}
    #MapLayer [id^="_"]:focus-visible {filter:brightness(1.2) saturate(1.2);outline:none}
    #BriefLabelLayer,#UnitLayer,#SupplyCenterLayer {pointer-events:none}
    '''
    for power, color in COLORS.items():
        style += f'.{power.lower()} {{fill:{TERRITORY_COLORS[power]};stroke:#81796b;stroke-width:1.5}} .unit{power.lower()} {{fill:{color};stroke:{UNIT_EDGES[power]};stroke-width:4;stroke-linejoin:round;fill-opacity:1}}'
    svg = svg.replace('</style>', style + '</style>')
    # All geographic hit targets have accessible names and can be used without a mouse.
    regions=map_schema()['regions']
    names = {r['id']: r['name'] for r in regions}
    home_powers={r['id']:r['home_power'] for r in regions if r['home_power']}
    def target(match):
        loc = SVG_ALIASES.get(match.group(1).upper(),match.group(1).upper())
        if loc not in names:
            return match.group(0)
        owner = territory_owner(game,loc)
        color = TERRITORY_COLORS[owner] if owner else '#eeebe3'
        if game.map.area_type(loc)=='WATER':
            color='#c6d8d5'
        return match.group(0)+f' data-province="{loc}" tabindex="0" role="button" aria-label="{names[loc]} ({loc})" style="fill:{color}"'
    svg = re.sub(r'id="_([a-z]{3})"', target, svg)
    if labels:
        def label(match):
            attrs, loc = match.groups()
            position=labels.get(loc)
            if not position:
                return match.group(0)
            attrs=re.sub(r'\s+(?:x|y|transform)="[^"]*"','',attrs)
            leader = f'<path d="M {position["x"]} {position["y"]+10} L {position["leader_to"][0]} {position["leader_to"][1]}" fill="none" stroke="#526d64" stroke-width="1.3"/>' if 'leader_to' in position else ''
            return leader+f'<text{attrs} x="{position["x"]}" y="{position["y"]}" dominant-baseline="middle" style="font-size:{position["font"]}px">{loc}</text>'
        svg=re.sub(r'<text\b([^>]*)>([A-Z]{3})</text>',label,svg)
    # Simple, original geometric pieces: circles for armies, triangles for fleets.
    for symbol,shape in [('Army','<circle cx="20" cy="20" r="16"/>'),('Fleet','<path d="M 20 3 L 38 36 L 2 36 Z"/>'),('DislodgedArmy','<circle cx="20" cy="20" r="16"/>'),('DislodgedFleet','<path d="M 20 3 L 38 36 L 2 36 Z"/>')]:
        svg=re.sub(fr'<symbol\b[^>]*id="{symbol}"[^>]*>.*?</symbol>',f'<symbol id="{symbol}" viewBox="0 0 40 40" overflow="visible">{shape}</symbol>',svg,flags=re.S)
    svg=re.sub(r'<symbol\b[^>]*id="SupplyCenter"[^>]*>.*?</symbol>','<symbol id="SupplyCenter" viewBox="-1 -1 12 12" overflow="visible"><path d="M 5 0 L 10 5 L 5 10 L 0 5 Z" fill="#fff8e5" stroke="#756546" stroke-width="1.2"/></symbol>',svg,flags=re.S)
    home_symbol='<symbol id="HomeSupplyCenter" viewBox="-1 -1 12 12" overflow="visible"><path d="M 5 0 L 10 5 L 5 10 L 0 5 Z" fill="#fff8e5" stroke="#655332" stroke-width="1.4"/><path d="M 5 2.7 L 7.3 5 L 5 7.3 L 2.7 5 Z" fill="#655332" stroke="none"/></symbol>'
    svg=svg.replace('</defs>',home_symbol+'</defs>',1)
    # Smaller, centered unit symbols leave room for the province labels in narrow provinces.
    def unit_symbol(match):
        attrs=match.group(1)
        center=re.search(r'id="sc_([A-Z]{3})"',attrs)
        if center:
            home=home_powers.get(center.group(1))
            if home:attrs=attrs.replace('#SupplyCenter','#HomeSupplyCenter')
            attrs+=f' data-center-type="{"home" if home else "ordinary"}" data-home-power="{home or ""}"'
            return '<use'+attrs+'/>'
        if not re.search(r'id="(?:unit_|dislodged_)',attrs):
            return match.group(0)
        loc_match=re.search(r'id="unit_([^"/]+)',attrs)
        size=labels.get(loc_match.group(1),{}).get('unit_size',28) if loc_match else 28
        for attr in ('x','y'):
            attrs=re.sub(fr'{attr}="([\d.]+)"',lambda m:f'{attr}="{float(m.group(1))+(40-size)/2}"',attrs)
        attrs=re.sub(r'(height|width)="40"',lambda m:f'{m.group(1)}="{size}"',attrs)
        return '<use'+attrs+'/>'
    svg=re.sub(r'<use\b([^>]*?)/>',unit_symbol,svg)
    svg=country_borders(svg,{r['id']:territory_owner(game,r['id']) for r in regions if r['terrain']!='WATER'},TERRITORY_COLORS)
    return draw_orders(svg, game.renderer, overlay_orders if overlay_orders is not None else game.get_orders(), results)


def territory_owner(game, loc):
    if loc in game.map.scs:
        return next((p for p in POWERS if loc in game.powers[p].centers),None)
    influenced=next((p for p in POWERS if loc in game.powers[p].influence),None)
    return influenced or next((p for p,locations in STARTING_TERRITORY.items() if loc in locations.split()),None)


def dbn_export(doc, game):
    """DBN 2022-02 wire format. Land IDs are title case in the published schema."""
    def province(loc):
        loc = loc.upper()[:3]
        return loc if game.map.area_type(loc) == 'WATER' else loc.title()

    def location(loc):
        parts = loc.split('/')
        return [province(parts[0]), parts[1].lower()] if len(parts) == 2 else province(loc)

    def convert_order(order):
        parts = order.split()
        if len(parts) < 3:
            return None
        unit, origin, action = parts[:3]
        if action == 'H':
            return 'h'
        if action in ('-', 'R'):
            return ['m', location(parts[3])]
        if action == 'S':
            return ['sm', location(parts[4]), location(parts[6])] if '-' in parts else ['sh', location(parts[4])]
        if action == 'C':
            return ['c', location(parts[4]), location(parts[6])]
        if action == 'B':
            return ['b', [unit, location(origin)]]
        if action == 'D':
            return 'd'
        return None

    def snapshot(state, phase, status, orders=None, results=None):
        if phase == 'COMPLETED':
            phase = doc['history'][-1]['name'] if doc['history'] else 'S1901M'
        record = dict(Phase=int(phase[1:5]) * 10 + {'S': 1, 'F': 2, 'W': 3}[phase[0]], Status=status,
                      CenterCounts={p.title(): len(state['centers'][p]) for p in POWERS},
                      SupplyCenters={p.title(): [province(loc) for loc in state['centers'][p]] for p in POWERS},
                      Units={p.title(): [[unit.split()[0], location(unit.split()[1])] for unit in state['units'][p] if not unit.startswith('*')] for p in POWERS},
                      DislodgedUnits=[province(unit.split()[1]) for p in POWERS for unit in state['retreats'][p]])
        if orders is not None:
            field = 'RetreatOrders' if phase.endswith('R') else 'Orders'
            record[field] = {}
            for power in POWERS:
                output = []
                for order in orders.get(power, []):
                    converted = convert_order(order)
                    if converted is None:
                        continue
                    outcome = [item for item in (results or {}).get(' '.join(order.split()[:2]), []) if item]
                    output.append([province(order.split()[1]), converted, ['f', ', '.join(outcome)] if outcome else 's'])
                record[field][power.title()] = output
        return record

    phases = [snapshot(h['state'], h['name'], 'Completed', h['orders'], h['results']) for h in doc['history']]
    phases.append(snapshot(game.get_state(), game.get_current_phase(), 'GameEnded' if game.is_game_done else 'AwaitingRetreats' if game.phase_type == 'R' else 'AwaitingOrders'))
    return dict(GameLabel=doc['title'], Modality='Online', CommunicationType='Full', Language='English', LimitType='Unlimited', AnonymityType='None', ScoringSystem='Unscored',
                Note='DBN 2022-02 format. Historical records contain beginning-of-phase positions and resolved orders. Unresolved orders are private and excluded. VIA convoy annotations remain available in the native export.',
                Players={p.title(): seat['name'] for p, seat in doc['seats'].items()}, GamePhases=phases)


DUMMY_HASH = generate_password_hash('unused-constant-time-login-placeholder')
app = create_app()

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=int(os.getenv('PORT', '8000')), debug=False)
