import json
import random
import pytest
from sqlalchemy import text
from diplomacy import Game
from app import create_app
from test_app import account
from drunk_power import automatic_orders

@pytest.fixture
def app(tmp_path):
    return create_app('sqlite:///'+str(tmp_path/'drunk.db'))

def table(app):
    host,hh=account(app,'host'); guest,gh=account(app,'guest')
    result=host.post('/api/games',json={'title':'Drunk Turkey','power':'FRANCE','drunk_power':'TURKEY'},headers=hh)
    assert result.status_code==201
    gid=result.json['id'];invite=host.get(f'/api/games/{gid}').json['invite']
    assert guest.post('/api/join',json={'code':invite,'power':'TURKEY'},headers=gh).status_code==409
    assert guest.post('/api/join',json={'code':invite,'power':'GERMANY'},headers=gh).status_code==200
    return host,hh,guest,gh,gid

def submit(client,headers,gid,power,orders,ready=True,phase='S1901M'):
    return client.put(f'/api/games/{gid}/orders',json=dict(power=power,orders=orders,ready=ready,phase=phase),headers=headers)

def resolve(client,headers,gid):
    state=client.get(f'/api/games/{gid}').json
    return client.post(f'/api/games/{gid}/adjudicate',json=dict(phase=state['phase'],revision=state['revision'],force=True),headers=headers)

def test_private_proposals_whole_sheet_selection_and_reset(app):
    host,hh,guest,gh,gid=table(app)
    assert submit(host,hh,gid,'TURKEY',['A CON - BUL','F ANK - BLA']).status_code==200
    assert submit(guest,gh,gid,'TURKEY',['A SMY - ARM']).status_code==200
    assert submit(host,hh,gid,'FRANCE',['A PAR - BUR']).status_code==200
    assert host.get(f'/api/games/{gid}').json['orders']['TURKEY']==['A CON - BUL','F ANK - BLA']
    assert guest.get(f'/api/games/{gid}').json['orders']['TURKEY']==['A SMY - ARM']
    assert submit(guest,gh,gid,'FRANCE',['A PAR H']).status_code==403
    assert resolve(host,hh,gid).status_code==200
    after=host.get(f'/api/games/{gid}').json
    selected=after['history'][0]['drunk_selection']
    assert selected['orders'] in [['A CON - BUL','F ANK - BLA'],['A SMY - ARM']]
    assert selected['player_number'] in [1,2]
    assert set(after['history'][0]['orders']['TURKEY'])==set(selected['orders'])
    assert 'A BUR' in after['state']['units']['FRANCE']
    assert after['orders']['TURKEY']==[]
    assert host.put(f'/api/games/{gid}/drunk-power',json={'power':'ITALY'},headers=hh).status_code==409

def test_skip_empty_unready_and_no_proposals(app):
    host,hh,guest,gh,gid=table(app)
    submit(host,hh,gid,'TURKEY',['A CON - BUL'],ready=False)
    submit(guest,gh,gid,'TURKEY',['A SMY - ARM'])
    resolve(host,hh,gid)
    after=host.get(f'/api/games/{gid}').json
    assert after['history'][0]['drunk_selection']['player_name']=='guest'
    resolve(host,hh,gid)
    assert host.get(f'/api/games/{gid}').json['history'][-1]['drunk_selection']['mode']=='no_proposal'

def test_host_setup_only_and_drunk_draw_rejected(app):
    host,hh,guest,gh,gid=table(app)
    assert guest.put(f'/api/games/{gid}/drunk-power',json={'power':'ITALY'},headers=gh).status_code==403
    assert host.put(f'/api/games/{gid}/drunk-power',json={'power':'GERMANY'},headers=hh).status_code==409
    assert host.put(f'/api/games/{gid}/drunk-power',json={'power':'ITALY'},headers=hh).status_code==200
    assert host.get(f'/api/games/{gid}').json['controlled']==['FRANCE','ITALY']
    assert host.put(f'/api/games/{gid}/orders',json=dict(power='ITALY',phase='S1901M',orders=[],draw=True),headers=hh).status_code==400

def test_random_builds_fill_centers_and_only_forced_removals():
    game=Game();game.clear_units('TURKEY');game.set_current_phase('W1901A')
    for seed in range(20):
        orders=automatic_orders(game,'TURKEY',random.Random(seed))
        assert len(orders)==3 and all(o.endswith(' B') for o in orders)
        assert {o.split()[1][:3] for o in orders}=={'ANK','SMY','CON'}
    game=Game();game.clear_centers('TURKEY');game.set_centers('TURKEY',['CON']);game.set_current_phase('W1901A')
    assert len(automatic_orders(game,'TURKEY'))==2
    assert all(o.endswith(' D') for o in automatic_orders(game,'TURKEY'))

def test_retreats_prefer_destinations_over_disbands():
    game=Game();game.clear_units();game.set_units('TURKEY',['A CON']);game.set_current_phase('S1901R')
    game.powers['TURKEY'].retreats={'A SMY':['ARM','SYR'],'A ANK':['ARM']}
    for seed in range(20):
        orders=automatic_orders(game,'TURKEY',random.Random(seed))
        assert len(orders)==2 and all(' R ' in o for o in orders)
        assert len({o.split()[-1] for o in orders})==2


def test_timer_uses_same_selection_once_and_automatic_adjustments(app):
    host,hh,guest,gh,gid=table(app)
    submit(guest,gh,gid,'TURKEY',['A CON - BUL'])
    with app.extensions['db'].begin() as conn:
        doc=json.loads(conn.execute(text('SELECT document FROM games WHERE id=:id'),{'id':gid}).scalar_one())
        doc['timer']={'enabled':True,'paused':False,'deadline':1,'token':'test','durations':{'opening':60,'movement':60,'retreat':60,'adjustment':60}}
        conn.execute(text('UPDATE games SET document=:d, revision=revision+1 WHERE id=:id'),{'id':gid,'d':json.dumps(doc)})
    after=host.get(f'/api/games/{gid}').json
    assert after['history'][0]['drunk_selection']['player_name']=='guest'
    assert after['history'][0]['automatic']
    assert len(host.get(f'/api/games/{gid}').json['history'])==1
    engine=Game();engine.clear_units('TURKEY');engine.set_current_phase('W1901A')
    with app.extensions['db'].begin() as conn:
        doc=json.loads(conn.execute(text('SELECT document FROM games WHERE id=:id'),{'id':gid}).scalar_one())
        doc['engine']=engine.to_dict();doc['timer']={}
        conn.execute(text('UPDATE games SET document=:d, revision=revision+1 WHERE id=:id'),{'id':gid,'d':json.dumps(doc)})
    view=host.get(f'/api/games/{gid}').json
    assert 'TURKEY' not in view['controlled']
    assert submit(host,hh,gid,'TURKEY',['A ANK B'],phase='W1901A').status_code==403
    assert resolve(host,hh,gid).status_code==200
    after=host.get(f'/api/games/{gid}').json
    assert len(after['state']['units']['TURKEY'])==3
    assert after['history'][-1]['drunk_selection']['mode']=='automatic'
