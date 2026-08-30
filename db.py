import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path("data/arena.db")

@contextmanager
def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()

def init_db():
    with connect() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS players(
          guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
          game_id TEXT, games INTEGER NOT NULL DEFAULT 0,
          wins INTEGER NOT NULL DEFAULT 0, losses INTEGER NOT NULL DEFAULT 0,
          kills INTEGER NOT NULL DEFAULT 0, deaths INTEGER NOT NULL DEFAULT 0,
          points INTEGER NOT NULL DEFAULT 1000,
          PRIMARY KEY(guild_id,user_id));
        CREATE TABLE IF NOT EXISTS matches(
          id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL,
          league TEXT NOT NULL, map TEXT NOT NULL, host_id INTEGER NOT NULL,
          team_a TEXT NOT NULL, team_b TEXT NOT NULL,
          score_a INTEGER, score_b INTEGER, lobby_url TEXT,
          status TEXT NOT NULL DEFAULT 'waiting', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS config(
          guild_id INTEGER PRIMARY KEY, payload TEXT NOT NULL);
        """)

def ensure_player(guild_id:int, user_id:int):
    with connect() as con:
        con.execute("INSERT OR IGNORE INTO players(guild_id,user_id) VALUES(?,?)", (guild_id,user_id))

def set_game_id(guild_id:int,user_id:int,game_id:str):
    ensure_player(guild_id,user_id)
    with connect() as con:
        con.execute("UPDATE players SET game_id=? WHERE guild_id=? AND user_id=?",(game_id,guild_id,user_id))

def player(guild_id:int,user_id:int):
    ensure_player(guild_id,user_id)
    with connect() as con:
        return dict(con.execute("SELECT * FROM players WHERE guild_id=? AND user_id=?",(guild_id,user_id)).fetchone())

def leaders(guild_id:int, limit:int=10):
    with connect() as con:
        return [dict(x) for x in con.execute("SELECT * FROM players WHERE guild_id=? ORDER BY points DESC,wins DESC LIMIT ?",(guild_id,limit))]

def create_match(guild_id,league,map_name,host_id,team_a,team_b):
    with connect() as con:
        cur=con.execute("INSERT INTO matches(guild_id,league,map,host_id,team_a,team_b) VALUES(?,?,?,?,?,?)",(guild_id,league,map_name,host_id,','.join(map(str,team_a)),','.join(map(str,team_b))))
        return cur.lastrowid

def match(match_id:int):
    with connect() as con:
        row=con.execute("SELECT * FROM matches WHERE id=?",(match_id,)).fetchone()
        return dict(row) if row else None

def set_lobby(match_id:int,url:str):
    with connect() as con:
        con.execute("UPDATE matches SET lobby_url=?,status='playing' WHERE id=?",(url,match_id))

def finish_match(match_id:int,score_a:int,score_b:int):
    with connect() as con:
        m=con.execute("SELECT * FROM matches WHERE id=? AND status!='finished'",(match_id,)).fetchone()
        if not m: return False
        a=[int(x) for x in m['team_a'].split(',')]; b=[int(x) for x in m['team_b'].split(',')]
        won_a=score_a>score_b
        for uid in a+b: con.execute("INSERT OR IGNORE INTO players(guild_id,user_id) VALUES(?,?)",(m['guild_id'],uid))
        for uid in a:
            con.execute("UPDATE players SET games=games+1,wins=wins+?,losses=losses+?,points=MAX(0,points+?) WHERE guild_id=? AND user_id=?",(1 if won_a else 0,0 if won_a else 1,25 if won_a else -18,m['guild_id'],uid))
        for uid in b:
            con.execute("UPDATE players SET games=games+1,wins=wins+?,losses=losses+?,points=MAX(0,points+?) WHERE guild_id=? AND user_id=?",(0 if won_a else 1,1 if won_a else 0,-18 if won_a else 25,m['guild_id'],uid))
        con.execute("UPDATE matches SET score_a=?,score_b=?,status='finished' WHERE id=?",(score_a,score_b,match_id))
        return True
