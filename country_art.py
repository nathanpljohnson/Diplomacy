"""Shared vector province edges and ownership-driven land frontiers.

Geometry is compiled from the standard map into a seamless polygon coverage.
No raster morphology filters: every boundary remains a resolution-independent path.
"""
import json
from pathlib import Path
from xml.dom import minidom

GEOMETRY = json.loads(Path(__file__).with_name('border_geometry.json').read_text())


def country_borders(svg, owners, palette):
    xml = minidom.parseString(svg)
    root = xml.documentElement
    root.setAttribute('shape-rendering', 'geometricPrecision')
    layer = next(g for g in root.getElementsByTagName('g') if g.getAttribute('id') == 'MapLayer')
    def node(tag, attrs, parent):
        n = xml.createElement(tag)
        for key, value in attrs.items():
            n.setAttribute(key, str(value))
        parent.appendChild(n)
        return n
    style = node('style', {}, root)
    style.appendChild(xml.createTextNode('#MapLayer path[data-province]{stroke:none!important;outline:none!important} #MapLayer path[data-province]:focus-visible{filter:brightness(1.2) saturate(1.2)}'))
    background = next(c for c in layer.childNodes if c.nodeType == c.ELEMENT_NODE and c.tagName == 'rect')
    background.setAttribute('fill', '#c6d8d5')
    aliases = {'NAT':'NAO','NRG':'NWG','MID':'MAO','GOL':'LYO','TYN':'TYS'}
    for path in layer.getElementsByTagName('path'):
        ident = path.getAttribute('id')
        if not ident.startswith('_'):
            continue
        code = aliases.get(ident[1:].upper(), ident[1:].upper())
        if code not in GEOMETRY['provinces']:
            continue
        path.setAttribute('d', GEOMETRY['provinces'][code])
        color = '#d1cfc7' if code == 'SWI' else palette.get(owners[code], '#eeebe3') if code in owners else '#c6d8d5'
        path.setAttribute('style', f'fill:{color}' + ('' if path.hasAttribute('data-province') else ';stroke:none'))
    common = {'fill':'none','stroke-linejoin':'round','stroke-linecap':'round','pointer-events':'none','aria-hidden':'true'}
    node('path', dict(common, id='ProvinceBorders', d=GEOMETRY['grid'], stroke='#7b827a', **{'stroke-width':1.1}), layer)
    outlines = node('g', {'id':'CountryBorders','pointer-events':'none','aria-hidden':'true'}, layer)
    groups = {power:node('g', {'data-border-power':power,'data-territories':' '.join(sorted(c for c,p in owners.items() if p == power))}, outlines) for power in palette}
    for a, b, edge in GEOMETRY['frontiers']:
        first, second = owners.get(a), owners.get(b)
        if first == second or not (first or second):
            continue
        node('path', dict(common, d=edge, stroke='#414b43', **{'stroke-width':2.6,'data-frontier':f'{a} {b}'}), groups[first or second])
    node('rect', {'x':195,'y':170,'width':1835,'height':1360,'fill':'none','stroke':'#716b58','stroke-width':2,'pointer-events':'none'}, layer)
    return root.toxml()
