"""Force a revision collision between all six independent player saves."""
from concurrent.futures import ThreadPoolExecutor
import threading
from sqlalchemy import event
from test_app import app,account


def test_six_simultaneous_sheets_merge_without_lost_orders(app):
    host,hh=account(app,'parallelhost')
    gid=host.post('/api/games',json={'title':'Concurrent table','host_only':True,'drunk_power':'TURKEY'},headers=hh).json['id']
    invite=host.get(f'/api/games/{gid}').json['invite']
    players=[]
    powers=['AUSTRIA','ENGLAND','FRANCE','GERMANY','ITALY','RUSSIA']
    for i,power in enumerate(powers):
        client,headers=account(app,'parallel'+str(i))
        assert client.post('/api/join',json={'code':invite,'power':power},headers=headers).status_code==200
        view=client.get(f'/api/games/{gid}').json
        unit=view['state']['units'][power][0]
        players.append((client,headers,power,[unit+' H']))
    for drunk in [False,True]:
        barrier=threading.Barrier(6);seen=threading.local()
        def collide(conn,cursor,statement,parameters,context,executemany):
            if statement.startswith('UPDATE games SET ') and 'document=' in statement and not getattr(seen,'waited',False):
                seen.waited=True;barrier.wait(timeout=15)
        event.listen(app.extensions['db'],'before_cursor_execute',collide)
        def save(item):
            client,headers,power,orders=item
            return client.put(f'/api/games/{gid}/orders',json={'phase':'S1901M','power':'TURKEY' if drunk else power,'orders':['A CON H'] if drunk else orders,'ready':True},headers=headers)
        try:
            with ThreadPoolExecutor(max_workers=6) as pool:
                responses=list(pool.map(save,players))
            assert [r.status_code for r in responses]==[200]*6,[r.json for r in responses]
        finally:
            event.remove(app.extensions['db'],'before_cursor_execute',collide)
        for client,headers,power,orders in players:
            view=client.get(f'/api/games/{gid}').json
            assert view['orders'][power]==orders and view['ready'][power]
            if drunk:assert view['orders']['TURKEY']==['A CON H'] and view['ready']['TURKEY']
