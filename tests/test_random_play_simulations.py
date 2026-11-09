"""Bounded, reproducible legal-order simulations through engine and app."""
import random
import xml.etree.ElementTree as ET
from diplomacy import Game
from app import POWERS
from test_app import app,account,make_game


def random_sheet(game,power,rng):
    possible=game.get_all_possible_orders()
    legal=sorted({o for loc in game.get_orderable_locations()[power] for o in possible.get(loc,[])})
    if game.phase_type=='A':
        count=game.get_state()['builds'][power]['count']
        if count<0:return rng.sample([o for o in legal if o.endswith(' D')],-count)
        centers={o.split()[1][:3] for o in legal if o.endswith(' B')}
        chosen=rng.sample(sorted(centers),min(count,len(centers)))
        return [rng.choice([o for o in legal if o.endswith(' B') and o.split()[1][:3]==c]) for c in chosen]
    units=game.get_state()['retreats'][power] if game.phase_type=='R' else game.get_state()['units'][power]
    return [rng.choice(options) for unit in units if (options:=[o for o in legal if o.startswith(unit.lstrip('*')+' ')])]


def invariant(game):
    state=game.get_state()
    units=[u.split()[1][:3] for sheet in state['units'].values() for u in sheet if not u.startswith('*')]
    assert len(units)==len(set(units))
    centers=[c for sheet in state['centers'].values() for c in sheet]
    assert len(centers)==len(set(centers)) and set(centers)<=set(game.map.scs)
    for power in POWERS:
        assert all(game.map.area_type(u.split()[1])!='SHUT' for u in state['units'][power])


def test_480_random_engine_phases():
    processed=0
    for seed in range(24):
        game=Game();rng=random.Random(seed)
        for _ in range(20):
            if game.is_game_done:break
            for p in POWERS:game.set_orders(p,random_sheet(game,p,rng))
            game.process();invariant(game);processed+=1
    assert processed>=400


def test_random_orders_round_trip_through_app(app):
    client,headers=account(app,'randomtable')
    for seed in range(4):
        gid=make_game(client,headers,True);rng=random.Random(seed+900)
        for phase_index in range(12):
            view=client.get(f'/api/games/{gid}').json
            if view['completed']:break
            engine=Game();engine.set_state(view['state'])
            for p in POWERS:
                orders=random_sheet(engine,p,rng)
                response=client.put(f'/api/games/{gid}/orders',json={'phase':view['phase'],'power':p,'orders':orders,'ready':True},headers=headers)
                assert response.status_code==200,(seed,view['phase'],p,orders,response.json)
            fresh=client.get(f'/api/games/{gid}').json
            resolved=client.post(f'/api/games/{gid}/adjudicate',json={'phase':fresh['phase'],'revision':fresh['revision']},headers=headers)
            assert resolved.status_code==200,(seed,fresh['phase'],resolved.json)
            after=client.get(f'/api/games/{gid}').json
            engine=Game();engine.set_state(after['state']);invariant(engine)
            assert len(after['history'])==phase_index+1
            if phase_index%4==0:
                response=client.get(f'/api/games/{gid}/map?results=1')
                assert response.status_code==200
                root=ET.fromstring(response.text)
                ns={'s':'http://www.w3.org/2000/svg'}
                assert len(root.findall('.//s:path[@data-province]',ns))==75
