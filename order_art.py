"""Original order overlays on the licensed standard map; adjudication stays in the engine."""
import math
import json
from pathlib import Path

ANCHORS = json.loads(Path(__file__).with_name('order_anchors.json').read_text())
from xml.dom import minidom


def draw_orders(svg, renderer, orders, results=None):
    xml=minidom.parseString(svg)
    root=xml.documentElement
    layer=next(node for node in root.getElementsByTagName('g') if node.getAttribute('id')=='OrderLayer')
    while layer.firstChild:layer.removeChild(layer.firstChild)
    layer.setAttribute('pointer-events','none')
    layer.setAttribute('data-resolved','true' if results is not None else 'false')
    defs=xml.createElement('defs');root.insertBefore(defs,root.firstChild)
    def element(tag,attrs,parent):
        node=xml.createElement(tag)
        for key,value in attrs.items():node.setAttribute(key,str(value))
        parent.appendChild(node);return node
    for status,color in [('white','#ffffff'),('red','#d63838')]:
        marker=element('marker',{'id':'entente-arrow-'+status,'viewBox':'0 0 12 12','refX':10,'refY':6,'markerWidth':3.2,'markerHeight':3.2,'orient':'auto'},defs)
        element('path',{'d':'M 1 1 L 11 6 L 1 11 Z','fill':color,'stroke':'#253d35','stroke-width':.6},marker)
    def center(loc, destination=False):
        if destination and loc in ANCHORS:
            return tuple(ANCHORS[loc]['center'])
        coord=renderer.metadata['coord'].get(loc) or renderer.metadata['coord'].get(loc[:3])
        if not coord:return None
        return tuple(float(v)+20 for v in coord['unit'])
    def unit(a,b):
        length=math.hypot(b[0]-a[0],b[1]-a[1]) or 1
        return ((b[0]-a[0])/length,(b[1]-a[1])/length),length
    def path(d,group,color,status,dotted=False,arrow=True):
        base={'d':d,'fill':'none','stroke-linecap':'round','stroke-linejoin':'round'}
        if dotted:base['stroke-dasharray']='1 11'
        element('path',{**base,'stroke':'#253d35','stroke-width':8,'opacity':.75,'class':'order-outline'},group)
        attrs={**base,'stroke':color,'stroke-width':5,'class':'order-ink'}
        if arrow:attrs['marker-end']='url(#entente-arrow-'+status+')'
        element('path',attrs,group)
    for power,sheet in orders.items():
        for order in sheet:
            tokens=order.split()
            if len(tokens)<3:continue
            origin=center(tokens[1]);kind=tokens[2]
            if not origin:continue
            outcomes=(results or {}).get(' '.join(tokens[:2]),[])
            failed=any(str(r).lower() not in ('','ok','success') for r in outcomes)
            status='red' if failed else 'white';color='#d63838' if failed else '#ffffff'
            group=element('g',{'data-order':order,'data-power':power,'data-failed':str(failed).lower(),'data-kind':kind},layer)
            title=element('title',{},group);title.appendChild(xml.createTextNode(order+(' · '+', '.join(outcomes) if outcomes else ' · resolved' if results is not None else ' · planned')))
            if kind in ('-','R'):
                dest=center(tokens[3], destination=True)
                if not dest:continue
                direction,length=unit(origin,dest);inset=min(18,length*.22,ANCHORS.get(tokens[3],{}).get('clearance',26)*.6)
                start=tuple(origin[i]+direction[i]*12 for i in (0,1));end=tuple(dest[i]-direction[i]*inset for i in (0,1))
                path(f'M {start[0]} {start[1]} L {end[0]} {end[1]}',group,color,status)
            elif kind in ('S','C'):
                supported_index=4 if tokens[3] in ('A','F') else 3
                source=center(tokens[supported_index]);moving='-' in tokens
                dest=center(tokens[-1] if moving else tokens[supported_index], destination=True)
                if not source or not dest:continue
                if moving:
                    direction,length=unit(source,dest);normal=(-direction[1],direction[0])
                    scale=min(1,ANCHORS.get(tokens[-1],{}).get('clearance',26)*.65/math.hypot(20,8))
                    end=tuple(dest[i]+(-direction[i]*20+normal[i]*8)*scale for i in (0,1))
                    reach=max(30,min(80,length*.4));control2=tuple(end[i]-direction[i]*reach for i in (0,1))
                    control1=tuple((origin[i]+source[i])/2+normal[i]*35 for i in (0,1))
                else:
                    direction,length=unit(origin,dest);normal=(-direction[1],direction[0])
                    inset=min(22,ANCHORS.get(tokens[supported_index],{}).get('clearance',26)*.65)
                    end=tuple(dest[i]-direction[i]*inset for i in (0,1))
                    control1=tuple(origin[i]+direction[i]*length*.3+normal[i]*35 for i in (0,1))
                    control2=tuple(end[i]-direction[i]*length*.3+normal[i]*35 for i in (0,1))
                toward,_=unit(origin,control1);start=tuple(origin[i]+toward[i]*14 for i in (0,1))
                path(f'M {start[0]} {start[1]} C {control1[0]} {control1[1]} {control2[0]} {control2[1]} {end[0]} {end[1]}',group,color,status,True)
            elif kind=='H':
                element('circle',{'cx':origin[0],'cy':origin[1],'r':20,'fill':'none','stroke':'#253d35','stroke-width':7},group)
                element('circle',{'cx':origin[0],'cy':origin[1],'r':20,'fill':'none','stroke':color,'stroke-width':4},group)
            if failed:
                # An explicit cross makes failure readable without relying on red alone.
                x,y=origin[0]+20,origin[1]-20
                path(f'M {x-7} {y-7} L {x+7} {y+7} M {x+7} {y-7} L {x-7} {y+7}',group,color,status,arrow=False)
    return root.toxml()
