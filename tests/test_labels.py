"""Layout data must cover the map without changing province geometry."""
import json,re
from app import ROOT,art_map
from diplomacy import Game


def test_label_manifest_and_callouts():
    positions=json.loads((ROOT/'map_labels.json').read_text())
    game=Game()
    provinces={loc.upper() for loc in game.map.locs if '/' not in loc}
    assert set(positions)==provinces
    assert all(not p.get('needs_review') for p in positions.values())
    svg=art_map(game)
    assert len(set(re.findall(r'data-province="([A-Z]{3})"',svg)))==75
    assert all('leader_to' in positions[loc] for loc in ['ROM','NAP','CLY'])
    assert positions['RUH']['unit_center']


def test_simple_army_and_fleet_shapes():
    import xml.etree.ElementTree as ET
    root=ET.fromstring(art_map(Game()))
    ns={'s':'http://www.w3.org/2000/svg'}
    for name in ['Army','DislodgedArmy']:
        symbol=root.find(f".//s:symbol[@id='{name}']",ns)
        assert symbol.get('viewBox')=='0 0 40 40'
        assert symbol.find('s:circle',ns) is not None
    for name in ['Fleet','DislodgedFleet']:
        symbol=root.find(f".//s:symbol[@id='{name}']",ns)
        assert symbol.get('viewBox')=='0 0 40 40'
        assert symbol.find('s:path',ns).get('d')=='M 20 3 L 38 36 L 2 36 Z'


def test_units_are_distinct_from_land_and_supply_centers():
    import xml.etree.ElementTree as ET
    from app import COLORS,TERRITORY_COLORS,UNIT_EDGES
    root=ET.fromstring(art_map(Game()));ns={'s':'http://www.w3.org/2000/svg'}
    units=[u for u in root.findall('.//s:use',ns) if u.get('id','').startswith('unit_')]
    centers=[u for u in root.findall('.//s:use',ns) if u.get('id','').startswith('sc_')]
    assert len(units)==22 and len(centers)==34
    assert root.find(".//s:symbol[@id='SupplyCenter']/s:path",ns) is not None
    assert all(COLORS[p]!=TERRITORY_COLORS[p]!=UNIT_EDGES[p] for p in COLORS)
    assert 'stroke-width:4' in ''.join(root.find('.//s:style',ns).itertext())


def test_home_center_markers_remain_original_after_capture():
    import xml.etree.ElementTree as ET
    from app import map_schema
    ns={'s':'http://www.w3.org/2000/svg'}
    g=Game();g.clear_centers('RUSSIA');g.set_centers('FRANCE',['WAR'])
    root=ET.fromstring(art_map(g))
    assert len(root.findall('.//s:use[@data-center-type="home"]',ns))==22
    assert len(root.findall('.//s:use[@data-center-type="ordinary"]',ns))==12
    war=root.find('.//s:use[@id="sc_WAR"]',ns)
    assert war.get('data-home-power')=='RUSSIA'
    assert war.get('{http://www.w3.org/1999/xlink}href')=='#HomeSupplyCenter'
    data={r['id']:r for r in map_schema()['regions']}
    assert data['PAR']['home_power']=='FRANCE'
    assert data['SPA']['home_power'] is None


def test_country_outlines_follow_held_provinces_and_keep_hit_geometry():
    import xml.etree.ElementTree as ET
    ns={'s':'http://www.w3.org/2000/svg'}
    g=Game();before=ET.fromstring(art_map(g))
    france=before.find('.//s:g[@data-border-power="FRANCE"]',ns)
    assert 'BEL' not in france.get('data-territories').split()
    original=before.find('.//s:path[@id="_bel"]',ns).get('d')
    g.set_centers('FRANCE',['PAR','MAR','BRE','BEL']);g.set_current_phase('W1901A')
    after=ET.fromstring(art_map(g));france=after.find('.//s:g[@data-border-power="FRANCE"]',ns)
    assert 'BEL' in france.get('data-territories').split()
    assert after.find('.//s:path[@id="_bel"]',ns).get('d')==original
    assert len(after.findall('.//s:path[@data-province]',ns))==75
    assert len(after.findall('.//s:g[@data-border-power]',ns))==7
    assert after.find('.//s:g[@id="MapLayer"]/s:rect',ns).get('fill')!='black'


def test_frontiers_are_vectors_and_follow_control_without_coastal_outlines():
    import xml.etree.ElementTree as ET
    ns={'s':'http://www.w3.org/2000/svg'}
    g=Game();before=ET.fromstring(art_map(g))
    assert before.find('.//s:path[@id="ProvinceBorders"]',ns) is not None
    borders=before.find('.//s:g[@id="CountryBorders"]',ns)
    assert borders.findall('.//s:path[@data-frontier]',ns)
    assert not borders.findall('.//*[@filter]')
    edges={frozenset(p.get('data-frontier').split()) for p in borders.findall('.//s:path',ns)}
    assert frozenset(['BEL','PIC']) in edges
    assert all(len(e)==2 for e in edges)
    g.set_centers('FRANCE',['PAR','MAR','BRE','BEL','HOL']);g.set_current_phase('W1901A')
    after=ET.fromstring(art_map(g))
    edges={frozenset(p.get('data-frontier').split()) for p in after.findall('.//s:g[@id="CountryBorders"]//s:path',ns)}
    assert frozenset(['BEL','PIC']) not in edges
    assert frozenset(['HOL','KIE']) in edges
    assert not after.findall('.//s:filter',ns)
