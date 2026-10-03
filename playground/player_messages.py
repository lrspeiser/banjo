"""World-scoped player messages, separate from private AI conversations."""
import hashlib
import re
import time

import player_world
import workshop_library

KEEP=200


def request(app, owner, body):
    if not isinstance(body,dict) or set(body)-{'action','message','request_id','after_id'}:
        raise ValueError('Player chat accepts list or send')
    action=body.get('action','list')
    if action not in ('list','send'):raise ValueError('Use list or send for player chat')
    after=body.get('after_id',0)
    if type(after) is not int or after<0:raise ValueError('Invalid message cursor')
    if action=='list' and set(body)-{'action','after_id'}:raise ValueError('Listing cannot send a message')
    if action=='send':
        message=body.get('message');ident=body.get('request_id')
        if not isinstance(message,str) or not message.strip() or len(message)>1000:
            raise ValueError('Write a player message of at most 1000 characters')
        if not isinstance(ident,str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,100}',ident):
            raise ValueError('Sending needs a message request id')
        message=message.strip();digest=hashlib.sha256(message.encode()).hexdigest()
    with player_world.lock_of(app):
        profile=player_world.records(app).get(owner)
        if not profile:raise ValueError('Join this world before chatting')
        name=profile['name']
    with workshop_library._connect(app) as db:
        db.execute('CREATE TABLE IF NOT EXISTS player_messages '
                   '(id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id TEXT, name TEXT, message TEXT, created_at REAL)')
        db.execute('CREATE TABLE IF NOT EXISTS player_message_receipts '
                   '(request_id TEXT PRIMARY KEY, owner_id TEXT, digest TEXT, message_id INTEGER)')
        repeated=False
        if action=='send':
            db.execute('BEGIN IMMEDIATE')
            receipt=db.execute('SELECT * FROM player_message_receipts WHERE request_id=?',(ident,)).fetchone()
            if receipt:
                if receipt['owner_id']!=owner or receipt['digest']!=digest:
                    raise ValueError('This message request belongs to another sender or message')
                repeated=True
            else:
                now=time.time()
                if db.execute('SELECT COUNT(*) FROM player_messages WHERE owner_id=? AND created_at>?',
                              (owner,now-2)).fetchone()[0]>=5:
                    raise ValueError('Give other players a moment before sending another message')
                row=db.execute('INSERT INTO player_messages(owner_id,name,message,created_at) VALUES (?,?,?,?)',
                               (owner,name,message,now))
                db.execute('INSERT INTO player_message_receipts VALUES (?,?,?,?)',(ident,owner,digest,row.lastrowid))
                db.execute('DELETE FROM player_messages WHERE id NOT IN '
                           '(SELECT id FROM player_messages ORDER BY id DESC LIMIT ?)',(KEEP,))
            db.commit()
        rows=db.execute('SELECT id,owner_id,name,message,created_at FROM player_messages WHERE id>? '
                        'ORDER BY id DESC LIMIT 50',(after,)).fetchall()
        cursor=db.execute('SELECT COALESCE(MAX(id),0) FROM player_messages').fetchone()[0]
        return {'messages':[dict(r) for r in reversed(rows)], 'cursor':cursor, 'repeated':repeated,
                'audience':'Players in this world', 'retained_messages':KEEP}
