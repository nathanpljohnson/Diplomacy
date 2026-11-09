import json
import pytest
from sqlalchemy import text
from diplomacy import Game
from app import create_app
import phase_clock
from test_app import account, make_game


@pytest.fixture
def app(tmp_path):
    return create_app('sqlite:///' + str(tmp_path/'features.db'))


def seed(app,gid,engine):
    with app.extensions['db'].begin() as conn:
        doc=json.loads(conn.execute(text('SELECT document FROM games WHERE id=:id'),{'id':gid}).scalar_one())
        doc['engine']=engine.to_dict()
        conn.execute(text('UPDATE games SET document=:doc WHERE id=:id'),{'id':gid,'doc':json.dumps(doc)})


@pytest.fixture
def scheduler(monkeypatch):
    clock=[1_800_000_000]
    messages=[]
    monkeypatch.setattr('app.time.time',lambda:clock[0])
    monkeypatch.setattr(phase_clock,'configured',lambda:True)
    monkeypatch.setattr(phase_clock,'verify',lambda signature,body:signature=='valid-test-signature')
    monkeypatch.setattr(phase_clock,'publish',lambda gid,token,phase,deadline,now:messages.append(dict(game_id=gid,token=token,phase=phase,deadline=deadline)))
    return clock,messages


def start(client,headers,gid):
    return client.post(f'/api/games/{gid}/timer',json={'action':'start','durations':dict.fromkeys(phase_clock.DEFAULT_DURATIONS,60)},headers=headers)


def test_durable_timer_pause_resume_and_exactly_once(app,scheduler):
    clock,messages=scheduler
    host,hh=account(app,'host');guest,gh=account(app,'guest')
    gid=make_game(host,hh)
    invite=host.get(f'/api/games/{gid}').json['invite']
    guest.post('/api/join',json={'code':invite,'power':'GERMANY'},headers=gh)
    assert start(guest,gh,gid).status_code==403
    assert start(host,hh,gid).status_code==200
    first=messages[-1]
    assert 'token' not in host.get(f'/api/games/{gid}').json['timer']
    assert host.post(f'/api/games/{gid}/timer',json={'action':'pause'},headers=hh).status_code==200
    clock[0]+=90
    assert host.post('/api/timer-callback',json=first,headers={'Upstash-Signature':'valid-test-signature'}).json['ignored']
    assert host.get(f'/api/games/{gid}').json['phase']=='S1901M'
    assert host.post(f'/api/games/{gid}/timer',json={'action':'resume'},headers=hh).status_code==200
    current=messages[-1]
    host.put(f'/api/games/{gid}/orders',json={'phase':'S1901M','power':'FRANCE','orders':['A PAR - BUR'],'ready':False},headers=hh)
    clock[0]+=61
    assert host.post('/api/timer-callback',json=current,headers={'Upstash-Signature':'valid-test-signature'}).status_code==200
    after=host.get(f'/api/games/{gid}').json
    assert after['phase']=='F1901M'
    assert 'A BUR' in after['state']['units']['FRANCE']
    assert after['history'][0]['automatic'] is True
    assert after['timer']['deadline']==clock[0]+60
    assert host.post('/api/timer-callback',json=current,headers={'Upstash-Signature':'valid-test-signature'}).json['ignored']
    assert host.get(f'/api/games/{gid}').json['phase']=='F1901M'
    assert host.put(f'/api/games/{gid}/orders',json={'phase':'S1901M','power':'FRANCE','orders':[]},headers=hh).status_code==409
    assert host.post('/api/timer-callback',json=messages[-1],headers={'Upstash-Signature':'forged'}).status_code==401


def test_empty_timer_phase_and_scheduler_failure(app,scheduler,monkeypatch):
    clock,_=scheduler
    host,headers=account(app,'host');gid=make_game(host,headers)
    assert start(host,headers,gid).status_code==200
    clock[0]+=61
    after=host.get(f'/api/games/{gid}').json
    assert after['phase']=='F1901M'
    assert after['history'][0]['orders']['FRANCE']==[]
    assert 'A PAR' in after['state']['units']['FRANCE']
    host.post(f'/api/games/{gid}/timer',json={'action':'stop'},headers=headers)
    def unavailable(*args):raise RuntimeError('offline')
    monkeypatch.setattr(phase_clock,'publish',unavailable)
    assert start(host,headers,gid).status_code==503
    assert host.get(f'/api/games/{gid}').json['timer']['enabled'] is False


def test_private_current_scenario_and_own_unsaved_draft(app):
    host,hh=account(app,'host');friend,fh=account(app,'friend')
    gid=make_game(host,hh)
    parent=host.get(f'/api/games/{gid}').json
    friend.post('/api/join',json={'code':parent['invite'],'power':'GERMANY'},headers=fh)
    friend.put(f'/api/games/{gid}/orders',json={'phase':'S1901M','power':'GERMANY','orders':['A MUN - BUR'],'ready':True},headers=fh)
    before=host.get(f'/api/games/{gid}').json
    response=host.post(f'/api/games/{gid}/scenarios',json={'phase':'S1901M','draft':{'power':'FRANCE','orders':['A PAR - BUR']}},headers=hh)
    assert response.status_code==201
    sid=response.json['id'];study=host.get(f'/api/games/{sid}').json
    assert study['sandbox'] and study['controlled']==study['powers']
    assert study['state']['units']==before['state']['units']
    assert study['orders']['FRANCE']==['A PAR - BUR']
    assert study['orders']['GERMANY']==[]
    assert not study['timer']
    assert friend.get(f'/api/games/{sid}').status_code==403
    assert host.post(f'/api/games/{sid}/adjudicate',json={'phase':study['phase'],'revision':study['revision'],'force':True},headers=hh).status_code==200
    assert 'A BUR' in host.get(f'/api/games/{sid}').json['state']['units']['FRANCE']
    unchanged=host.get(f'/api/games/{gid}').json
    assert unchanged['revision']==before['revision']
    assert unchanged['state']['units']==before['state']['units']
    assert host.post(f'/api/games/{gid}/scenarios',json={'draft':{'power':'GERMANY','orders':[]}},headers=hh).status_code==403
    second=host.post(f'/api/games/{gid}/scenarios',json={},headers=hh).json['id']
    assert second!=sid


def test_historical_scenario(app):
    host,headers=account(app,'host');gid=make_game(host,headers)
    host.put(f'/api/games/{gid}/orders',json={'phase':'S1901M','power':'FRANCE','orders':['A PAR - BUR'],'ready':True},headers=headers)
    game=host.get(f'/api/games/{gid}').json
    host.post(f'/api/games/{gid}/adjudicate',json={'phase':game['phase'],'revision':game['revision'],'force':True},headers=headers)
    sid=host.post(f'/api/games/{gid}/scenarios',json={'phase':'S1901M'},headers=headers).json['id']
    study=host.get(f'/api/games/{sid}').json
    assert study['phase']=='S1901M'
    assert 'A PAR' in study['state']['units']['FRANCE']
    assert study['orders']['FRANCE']==['A PAR - BUR']


def test_draw_instead_of_moves_and_unanimous_finish(app):
    host,headers=account(app,'host');gid=make_game(host,headers,True)
    engine=Game();engine.clear_units();engine.clear_centers()
    engine.set_units('FRANCE',['A PAR']);engine.set_centers('FRANCE',['PAR'])
    engine.set_units('GERMANY',['A MUN']);engine.set_centers('GERMANY',['MUN'])
    seed(app,gid,engine)
    def sheet(power,orders,draw=False):
        phase=host.get(f'/api/games/{gid}').json['phase']
        return host.put(f'/api/games/{gid}/orders',json={'phase':phase,'power':power,'orders':orders,'draw':draw,'ready':True},headers=headers)
    assert sheet('FRANCE',['A PAR - BUR'],True).status_code==400
    assert sheet('FRANCE',[],True).status_code==200
    assert sheet('GERMANY',['A MUN - BUR']).status_code==200
    game=host.get(f'/api/games/{gid}').json
    host.post(f'/api/games/{gid}/adjudicate',json={'phase':game['phase'],'revision':game['revision'],'force':True},headers=headers)
    after=host.get(f'/api/games/{gid}').json
    assert not after['completed']
    assert 'A PAR' in after['state']['units']['FRANCE']
    assert 'A BUR' in after['state']['units']['GERMANY']
    assert after['history'][0]['draw_offers']==['FRANCE']
    assert sheet('FRANCE',[],True).status_code==200
    assert sheet('GERMANY',[],True).status_code==200
    game=host.get(f'/api/games/{gid}').json
    response=host.post(f'/api/games/{gid}/adjudicate',json={'phase':game['phase'],'revision':game['revision'],'force':True},headers=headers)
    assert response.status_code==200,response.json
    done=host.get(f'/api/games/{gid}').json
    assert done['completed'] and done['ended_reason']=='draw'
    assert host.put(f'/api/games/{gid}/orders',json={'phase':done['phase'],'power':'FRANCE','orders':[]},headers=headers).status_code==409
    assert host.post(f'/api/games/{gid}/adjudicate',json={'phase':done['phase'],'revision':done['revision'],'force':True},headers=headers).status_code==409


def test_host_only_role_and_map_click_targets(app):
    host,headers=account(app,'host')
    response=host.post('/api/games',json={'title':'Hosted table','power':'FRANCE','host_only':True},headers=headers)
    game=host.get('/api/games/'+response.json['id']).json
    assert game['host'] and game['controlled']==[] and game['seats']=={}
    svg=host.get('/api/games/'+game['id']+'/map').text
    import re
    assert len(set(re.findall(r'data-province="([A-Z]{3})"',svg)))==75
    for code in ['MAO','NAO','NWG','LYO','TYS','STP','BUL','SPA']:
        assert f'data-province="{code}"' in svg


def test_center_colors_stay_with_owner_until_fall():
    from app import territory_owner
    engine=Game();engine.set_units('GERMANY',['A PAR'])
    assert territory_owner(engine,'PAR')=='FRANCE'
    engine.set_centers('GERMANY',['PAR'])
    assert territory_owner(engine,'PAR')=='GERMANY'
    assert territory_owner(engine,'GAS')=='FRANCE'


def test_build_planner_legal_sites_coasts_and_limits(app):
    host,headers=account(app,'buildhost');gid=make_game(host,headers,True)
    g=Game();g.clear_units('RUSSIA');g.set_units('RUSSIA',['A MOS','A UKR'])
    g.set_centers('RUSSIA',['MOS','WAR','STP','SEV','SPA']);g.set_current_phase('W1901A')
    seed(app,gid,g)
    data=host.get(f'/api/games/{gid}').json['construction']['RUSSIA']
    assert data['count']==3
    sites={c['province']:c for c in data['centers']}
    assert sites['SPA']['orders']==[] and not sites['SPA']['home']
    assert sites['MOS']['orders']==[] and sites['MOS']['occupied']
    assert sites['WAR']['orders']==['A WAR B'] # Inland: never offer a fleet.
    assert set(sites['STP']['orders'])=={'A STP B','F STP/NC B','F STP/SC B'}
    assert set(sites['SEV']['orders'])=={'A SEV B','F SEV B'}
    base={'phase':'W1901A','power':'RUSSIA','ready':True}
    assert host.put(f'/api/games/{gid}/orders',json={**base,'orders':['F WAR B']},headers=headers).status_code==400
    assert host.put(f'/api/games/{gid}/orders',json={**base,'orders':['A SPA B']},headers=headers).status_code==400
    assert host.put(f'/api/games/{gid}/orders',json={**base,'orders':['F STP B']},headers=headers).status_code==400
    assert host.put(f'/api/games/{gid}/orders',json={**base,'orders':['F STP/NC B','F STP/SC B']},headers=headers).status_code==400
    assert host.put(f'/api/games/{gid}/orders',json={**base,'orders':['A WAR B','F STP/SC B','F SEV B']},headers=headers).status_code==200
    before=host.get(f'/api/games/{gid}').json
    assert 'F STP/SC' not in before['state']['units']['RUSSIA']
    assert host.post(f'/api/games/{gid}/adjudicate',json={'phase':before['phase'],'revision':before['revision'],'force':True},headers=headers).status_code==200
    after=host.get(f'/api/games/{gid}').json
    assert 'F STP/SC' in after['state']['units']['RUSSIA']
    assert 'A WAR' in after['state']['units']['RUSSIA']
    assert after['construction']=={}


def test_retreat_choices_only_for_actual_displaced_units(app):
    host,hh=account(app,'safehost');guest,gh=account(app,'retreater')
    gid=make_game(host,hh);invite=host.get(f'/api/games/{gid}').json['invite']
    guest.post('/api/join',json={'code':invite,'power':'GERMANY'},headers=gh)
    g=Game();g.clear_units();g.set_units('FRANCE',['A BUR','A GAS']);g.set_units('GERMANY',['A PAR'])
    g.set_orders('FRANCE',['A BUR - PAR','A GAS S A BUR - PAR']);g.process();seed(app,gid,g)
    assert host.get(f'/api/games/{gid}').json['retreat_options']=={'FRANCE':[]}
    displaced=guest.get(f'/api/games/{gid}').json['retreat_options']['GERMANY']
    assert len(displaced)==1 and displaced[0]['unit']=='A PAR'
    assert set(displaced[0]['orders'])=={'A PAR R BRE','A PAR R PIC','A PAR D'}
    base={'phase':'S1901R','power':'GERMANY','ready':True}
    assert guest.put(f'/api/games/{gid}/orders',json={**base,'orders':['A PAR R BUR']},headers=gh).status_code==400
    assert guest.put(f'/api/games/{gid}/orders',json={**base,'orders':['A PAR R PIC']},headers=gh).status_code==200
    game=host.get(f'/api/games/{gid}').json
    host.post(f'/api/games/{gid}/adjudicate',json={'phase':game['phase'],'revision':game['revision'],'force':True},headers=hh)
    after=guest.get(f'/api/games/{gid}').json
    assert 'A PIC' in after['state']['units']['GERMANY'] and after['retreat_options']=={}
