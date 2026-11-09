import json,threading
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import text,event
from test_app import app,account,make_game
import phase_clock


def test_six_simultaneous_deadline_callbacks_resolve_only_once(app,monkeypatch):
    clock=1_800_000_000
    monkeypatch.setattr('app.time.time',lambda:clock)
    monkeypatch.setattr(phase_clock,'verify',lambda *args:True)
    monkeypatch.setattr(phase_clock,'publish',lambda *args:None)
    host,headers=account(app,'callbackrace');gid=make_game(host,headers)
    with app.extensions['db'].begin() as c:
        doc=json.loads(c.execute(text('SELECT document FROM games WHERE id=:id'),{'id':gid}).scalar_one())
        doc['timer']={'enabled':True,'paused':False,'deadline':clock-1,'token':'same-delivery','durations':dict(opening=60,movement=60,retreat=60,adjustment=60)}
        c.execute(text('UPDATE games SET document=:d WHERE id=:id'),{'id':gid,'d':json.dumps(doc)})
    barrier=threading.Barrier(6);local=threading.local()
    def collide(conn,cursor,statement,parameters,context,executemany):
        if statement.startswith('UPDATE games SET ') and 'document=' in statement and not getattr(local,'waited',False):
            local.waited=True;barrier.wait(timeout=15)
    event.listen(app.extensions['db'],'before_cursor_execute',collide)
    def callback(_):
        return app.test_client().post('/api/timer-callback',json={'game_id':gid,'token':'same-delivery','phase':'S1901M'},headers={'Upstash-Signature':'test'})
    try:
        with ThreadPoolExecutor(max_workers=6) as pool:responses=list(pool.map(callback,range(6)))
        assert [r.status_code for r in responses]==[200]*6,[r.json for r in responses]
    finally:event.remove(app.extensions['db'],'before_cursor_execute',collide)
    view=host.get(f'/api/games/{gid}').json
    assert view['phase']=='F1901M' and len(view['history'])==1
    assert view['history'][0]['automatic']
    stale=host.post(f'/api/games/{gid}/adjudicate',json={'phase':'S1901M','revision':0,'force':True},headers=headers)
    assert stale.status_code==409
    assert len(host.get(f'/api/games/{gid}').json['history'])==1
