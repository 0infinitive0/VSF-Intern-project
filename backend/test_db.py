import sqlite3
import json
import os

db_path = 'd:\\Git repo\\vsf-project\\backend\\data\\session_store.db'
if not os.path.exists(db_path):
    print('DB not found')
else:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT history FROM sessions WHERE session_id = 'b44d6afe-e9fb-476f-8bec-c583fd123cc2'")
    row = cur.fetchone()
    if row:
        history = json.loads(row[0])
        for m in history:
            print(f"[{m.get('type')}] {m.get('content')}")
    else:
        print('Session not found in DB')
