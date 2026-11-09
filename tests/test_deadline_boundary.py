"""A request loaded before expiry must not save after the deadline."""
import json,time
from sqlalchemy import event,text
from test_app import app,account,make_game


def test_delayed_write_cannot_cross_timer_deadline(app):
    host,headers=account(app,'deadlinehost');gid=make_game(host,headers)
    deadline=int(time.time())+2
    with app.extensions['db'].begin() as c:
        doc=json.loads(c.execute(text('SELECT document FROM games WHERE id=:id'),{'id':gid}).scalar_one())
        doc['timer']={'enabled':True,'paused':False,'deadline':deadline,'token':'boundary','durations':dict(opening=60,movement=60,retreat=60,adjustment=60)}
        c.execute(text('UPDATE games SET document=:d WHERE id=:id'),{'id':gid,'d':json.dumps(doc)})
    delayed=[False]
    def delay(conn,cursor,statement,parameters,context,executemany):
        if statement.startswith('UPDATE games SET ') and 'document=' in statement and "strftime" in statement and not delayed[0]:
            delayed[0]=True
            while time.time()<deadline+.03:time.sleep(.01)
    event.listen(app.extensions['db'],'before_cursor_execute',delay)
    try:
        r=host.put(f'/api/games/{gid}/orders',json={'phase':'S1901M','power':'FRANCE','orders':['A PAR - BUR'],'ready':True},headers=headers)
    finally:event.remove(app.extensions['db'],'before_cursor_execute',delay)
    assert delayed[0] and r.status_code==409,(r.status_code,r.json)
    view=host.get(f'/api/games/{gid}').json
    assert view['phase']=='F1901M' and 'A PAR' in view['state']['units']['FRANCE']
    assert 'A PAR - BUR' not in view['history'][0]['orders']['FRANCE']
