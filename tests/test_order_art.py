import xml.etree.ElementTree as ET
from diplomacy import Game
from app import art_map
from test_app import account,make_game,app

NS={'s':'http://www.w3.org/2000/svg'}

def overlays(svg):
    root=ET.fromstring(svg)
    return {node.get('data-order'):node for node in root.findall('.//s:g[@data-order]',NS)}


def test_white_moves_curved_dotted_support_and_independent_outcomes():
    g=Game();g.set_orders('FRANCE',['A PAR - BUR','A MAR S A PAR - BUR'])
    nodes=overlays(art_map(g,results={'A PAR':['bounce']}))
    move=nodes['A PAR - BUR'];support=nodes['A MAR S A PAR - BUR']
    assert move.get('data-failed')=='true'
    assert support.get('data-failed')=='false' # A valid support is not a failed attack.
    assert move.find("s:path[@class='order-ink']",NS).get('stroke')=='#d63838'
    ink=support.find("s:path[@class='order-ink']",NS)
    assert ink.get('stroke')=='#ffffff' and ink.get('stroke-dasharray')
    assert ' C ' in ink.get('d')
    planned=overlays(art_map(g))
    assert planned['A PAR - BUR'].find("s:path[@class='order-ink']",NS).get('stroke')=='#ffffff'


def test_result_arrows_on_resulting_position_and_history(app):
    host,headers=account(app,'arrowhost');gid=make_game(host,headers,True)
    for power,sheet in [('FRANCE',['A PAR - BUR']),('GERMANY',['A MUN - BUR','F KIE - DEN'])]:
        assert host.put(f'/api/games/{gid}/orders',json={'phase':'S1901M','power':power,'orders':sheet,'ready':True},headers=headers).status_code==200
    before=host.get(f'/api/games/{gid}').json
    assert host.post(f'/api/games/{gid}/adjudicate',json={'phase':before['phase'],'revision':before['revision'],'force':True},headers=headers).status_code==200
    result=host.get(f'/api/games/{gid}/map?results=1')
    assert result.status_code==200
    nodes=overlays(result.text)
    assert nodes['A PAR - BUR'].get('data-failed')=='true'
    assert nodes['A MUN - BUR'].get('data-failed')=='true'
    assert nodes['F KIE - DEN'].get('data-failed')=='false'
    assert 'id="unit_DEN"' in result.text
    historical=host.get(f'/api/games/{gid}/map?phase=S1901M').text
    assert overlays(historical)['A PAR - BUR'].get('data-failed')=='true'
    assert 'id="unit_KIE"' in historical
    assert not overlays(host.get(f'/api/games/{gid}/map').text)


def test_all_arrow_destinations_stay_inside_their_province():
    """Audit every province/coast, approached from around the board.

    These are rendering probes, not orders sent to the rules engine. Each
    approach exercises endpoint insets for movement, retreat, support, convoy.
    """
    import json,re
    from pathlib import Path
    from order_art import ANCHORS,draw_orders
    geometry=json.loads(Path('border_geometry.json').read_text())['provinces']
    rings={code:[[(float(x),float(y)) for x,y in re.findall(r'([-\d.]+),([-\d.]+)',ring)] for ring in d.split('M ')[1:]] for code,d in geometry.items()}
    def inside(code,x,y):
        x+=195;y+=170
        contained=False
        for ring in rings[code]:
            for (ax,ay),(bx,by) in zip(ring,ring[1:]+ring[:1]):
                if (ay>y)!=(by>y) and x<(bx-ax)*(y-ay)/(by-ay)+ax:
                    contained=not contained
        return contained
    g=Game();base=art_map(g)
    origins=['NAO','NWG','STP','MOS','SEV','SYR','EAS','TUN','MAO','GRE']
    probes={}
    for dest in ANCHORS:
        for origin in origins:
            if origin[:3]==dest[:3]:continue
            for order in [f'F {origin} - {dest}',f'F {origin} R {dest}',f'F {origin} S F NAO - {dest}',f'F {origin} C A LON - {dest}',f'F {origin} S F {dest}']:
                probes[order]=dest
    nodes=overlays(draw_orders(base,g.renderer,{'FRANCE':list(probes)}))
    assert len(nodes)==len(probes)
    for order,dest in probes.items():
        ink=nodes[order].find("s:path[@class='order-ink']",NS)
        numbers=re.findall(r'[-+]?(?:\d*\.?\d+)(?:[eE][-+]?\d+)?',ink.get('d'))
        x,y=map(float,numbers[-2:])
        assert inside(dest[:3],x,y),(order,x,y)


def test_greece_to_bulgaria_south_coast_points_into_bulgaria():
    from order_art import ANCHORS
    g=Game();g.clear_units('TURKEY');g.set_units('ITALY',['F GRE'])
    g.set_orders('ITALY',['F GRE - BUL/SC'])
    svg=art_map(g)
    node=overlays(svg)['F GRE - BUL/SC']
    assert node.find("s:path[@class='order-ink']",NS) is not None
    # The old anchor was offshore at (1090,1160). Keep coast selection explicit.
    assert ANCHORS['BUL/SC']['center'][1]<1120
    assert ANCHORS['BUL/SC']['center']!=ANCHORS['BUL/EC']['center']
