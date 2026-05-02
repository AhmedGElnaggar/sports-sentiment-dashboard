from flask import Flask, jsonify, render_template
from flask_cors import CORS
import requests
import sqlite3
import time
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

# CONFIG
FOOTBALL_API_KEY = os.getenv("FOOTBALL_API_KEY", "")
FOOTBALL_BASE    = "https://api.football-data.org/v4"
REDDIT_BASE      = "https://www.reddit.com"

LEAGUES = {
    "PL":  {"name": "Premier League",   "flag": "🏴󠁧󠁢󠁥󠁮󠁧󠁿"},
    "PD":  {"name": "La Liga",          "flag": "🇪🇸"},
    "CL":  {"name": "Champions League", "flag": "🏆"},
    "BL1": {"name": "Bundesliga",       "flag": "🇩🇪"},
    "SA":  {"name": "Serie A",          "flag": "🇮🇹"},
    "WC":  {"name": "World Cup",        "flag": "🌍"},
}

REDDIT_SUBS = ["soccer", "PremierLeague", "laliga", "ChampionsLeague", "bundesliga"]

DB_PATH = "sports.db"

# DATABASE
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS matches (
        id INTEGER PRIMARY KEY,
        league TEXT,
        home_team TEXT,
        away_team TEXT,
        home_score INTEGER,
        away_score INTEGER,
        status TEXT,
        match_date TEXT,
        fetched_at TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS sentiment (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        subreddit TEXT,
        title TEXT,
        score INTEGER,
        sentiment TEXT,
        sentiment_score REAL,
        fetched_at TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS standings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        league TEXT,
        position INTEGER,
        team TEXT,
        played INTEGER,
        won INTEGER,
        draw INTEGER,
        lost INTEGER,
        points INTEGER,
        fetched_at TEXT
    )''')
    conn.commit()
    conn.close()

# SENTIMENT ANALYSIS
POSITIVE_WORDS = set([
    "win", "won", "beat", "victory", "dominated", "thrashed", "hammered",
    "destroyed", "crushed", "demolished", "thumped", "drubbed", "dismantled",
    "outclassed", "masterclass",
    "goal", "goals", "brace", "hattrick", "hat-trick", "screamer", "worldie",
    "assist", "assists", "clinical", "brilliant", "superb", "outstanding",
    "excellent", "fantastic", "incredible", "unreal", "insane", "fire",
    "class", "quality", "perfect", "immense", "elite", "goat",
    "great", "amazing", "awesome", "love", "best", "top", "legend",
    "legendary", "proud", "excited", "happy", "joy", "celebrate",
    "celebration", "deserved", "dominant", "impressive", "solid",
    "clean", "flawless", "unstoppable", "dangerous", "sharp",
    "champion", "champions", "trophy", "title", "treble", "double",
    "unbeaten", "comeback", "saved", "heroic", "hero", "clutch",
    "signed", "signing", "deal", "upgrade",
])

NEGATIVE_WORDS = set([
    "loss", "lost", "defeat", "beaten", "thrashed", "humiliated",
    "embarrassed", "hammered", "destroyed", "relegated", "relegation",
    "eliminated", "knocked", "out",
    "terrible", "awful", "worst", "poor", "bad", "disappointing",
    "disaster", "pathetic", "shocking", "useless", "rubbish", "trash",
    "garbage", "dire", "disgraceful", "dreadful", "horrendous",
    "abysmal", "woeful", "hopeless", "weak", "slow", "passive",
    "toothless", "boring", "inconsistent", "sloppy", "shambolic",
    "sacked", "fired", "resign", "resigned", "quit", "toxic",
    "crisis", "chaos", "drama", "mess", "scandal",
    "failed", "failure", "joke", "clown", "fraud", "overrated",
    "bottled", "bottle", "choke", "choked", "capitulate",
    "injured", "injury", "suspended", "suspension", "ban", "banned",
    "miss", "missing", "doubt", "concern",
    "embarrassment", "laughingstock", "fuming", "furious",
    "disgusted", "frustrated", "done", "finished",
])

def analyze_sentiment(text):
    text_lower = text.lower()
    words = text_lower.split()
    pos = sum(1 for w in words if w in POSITIVE_WORDS)
    neg = sum(1 for w in words if w in NEGATIVE_WORDS)
    total = pos + neg
    if total == 0:
        return "neutral", 0.0
    score = (pos - neg) / total
    if score > 0.1:
        return "positive", round(score, 2)
    elif score < -0.1:
        return "negative", round(score, 2)
    return "neutral", round(score, 2)

def get_team_name(team_obj):
    return (
        team_obj.get("shortName") or
        team_obj.get("name") or
        team_obj.get("tla") or
        "TBD"
    )

# Cache
_matches_cache   = {"data": {}, "timestamp": 0}
_standings_cache = {"data": {}, "timestamp": 0}
CACHE_TTL = 300

def fetch_matches(league_code):
    headers = {"X-Auth-Token": FOOTBALL_API_KEY}
    try:
        date_from = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
        date_to   = (datetime.utcnow() + timedelta(days=7)).strftime("%Y-%m-%d")
        res = requests.get(
            f"{FOOTBALL_BASE}/competitions/{league_code}/matches",
            params={"dateFrom": date_from, "dateTo": date_to},
            headers=headers, timeout=10
        )
        if res.status_code != 200:
            print(f"Football API {res.status_code}: {res.text}")
            return []
        data = res.json()
        matches = []
        for m in data.get("matches", [])[:10]:
            matches.append({
                "id":         m["id"],
                "home":       get_team_name(m["homeTeam"]),
                "away":       get_team_name(m["awayTeam"]),
                "home_score": m["score"]["fullTime"]["home"],
                "away_score": m["score"]["fullTime"]["away"],
                "status":     m["status"],
                "date":       m["utcDate"][:10],
                "time":       m["utcDate"][11:16],
            })
        # Save to database
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        for m in matches:
            c.execute('''INSERT OR REPLACE INTO matches
                (id, league, home_team, away_team, home_score, away_score, status, match_date, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (m["id"], league_code, m["home"], m["away"],
                 m["home_score"], m["away_score"], m["status"],
                 m["date"], datetime.utcnow().isoformat()))
        conn.commit()
        conn.close()
        return matches
    except Exception as e:
        print(f"Football API error: {e}")
        return []
def fetch_standings(league_code):
    headers = {"X-Auth-Token": FOOTBALL_API_KEY}
    try:
        res = requests.get(
            f"{FOOTBALL_BASE}/competitions/{league_code}/standings",
            headers=headers, timeout=10
        )
        if res.status_code != 200:
            print(f"Standings API {res.status_code}: {res.text}")
            return []
        data = res.json()
        table = data.get("standings", [{}])[0].get("table", [])
        result = [{
            "pos":    t["position"],
            "team":   get_team_name(t["team"]),
            "played": t["playedGames"],
            "won":    t["won"],
            "draw":   t["draw"],
            "lost":   t["lost"],
            "points": t["points"],
            "gd":     t["goalDifference"],
        } for t in table[:10]]
        # Save to database
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("DELETE FROM standings WHERE league = ?", (league_code,))
        for t in result:
            c.execute('''INSERT INTO standings 
                (league, position, team, played, won, draw, lost, points, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (league_code, t["pos"], t["team"], t["played"],
                 t["won"], t["draw"], t["lost"], t["points"],
                 datetime.utcnow().isoformat()))
        conn.commit()
        conn.close()
        return result
    except Exception as e:
        print(f"Standings error: {e}")
        return []

def fetch_reddit_sentiment(subreddit):
    try:
        headers = {"User-Agent": "AE-Sports-Dashboard/1.0"}
        res = requests.get(
            f"{REDDIT_BASE}/r/{subreddit}/hot.json?limit=25",
            headers=headers, timeout=10
        )
        if res.status_code != 200:
            return []
        posts = res.json().get("data", {}).get("children", [])
        results = []
        for p in posts[:15]:
            d = p["data"]
            title     = d.get("title", "")
            score     = d.get("score", 0)
            sentiment, s_score = analyze_sentiment(title)
            results.append({
                "title":           title[:120],
                "score":           score,
                "sentiment":       sentiment,
                "sentiment_score": s_score,
                "url":             f"https://reddit.com{d.get('permalink', '')}"
            })
        return results
    except Exception as e:
        print(f"Reddit error: {e}")
        return []

def fetch_match_detail(match_id):
    headers = {"X-Auth-Token": FOOTBALL_API_KEY}
    try:
        res = requests.get(
            f"{FOOTBALL_BASE}/matches/{match_id}",
            headers=headers, timeout=10
        )
        if res.status_code != 200:
            print(f"Match detail API {res.status_code}: {res.text}")
            return None
        m = res.json()

        goals = []
        for g in m.get("goals", []):
            goals.append({
                "minute": g.get("minute"),
                "scorer": g.get("scorer", {}).get("name", "Unknown"),
                "assist": g.get("assist", {}).get("name") if g.get("assist") else None,
                "team":   get_team_name(g.get("team", {})),
                "type":   g.get("type", "REGULAR"),
            })

        bookings = []
        for b in m.get("bookings", []):
            bookings.append({
                "minute": b.get("minute"),
                "player": b.get("player", {}).get("name", "Unknown"),
                "team":   get_team_name(b.get("team", {})),
                "card":   b.get("card"),
            })

        subs = []
        for s in m.get("substitutions", []):
            subs.append({
                "minute":     s.get("minute"),
                "player_out": s.get("playerOut", {}).get("name", "Unknown"),
                "player_in":  s.get("playerIn",  {}).get("name", "Unknown"),
                "team":       get_team_name(s.get("team", {})),
            })

        home_lineup = []
        away_lineup = []
        for lineup in m.get("lineups", []):
            players = [{
                "name":     p.get("name", "Unknown"),
                "position": p.get("position", ""),
                "shirt":    p.get("shirtNumber"),
            } for p in lineup.get("startXI", [])]
            if lineup.get("team", {}).get("id") == m["homeTeam"]["id"]:
                home_lineup = players
            else:
                away_lineup = players

        return {
            "id":            m["id"],
            "competition":   m.get("competition", {}).get("name", ""),
            "matchday":      m.get("matchday"),
            "home":          get_team_name(m["homeTeam"]),
            "away":          get_team_name(m["awayTeam"]),
            "home_score":    m["score"]["fullTime"]["home"],
            "away_score":    m["score"]["fullTime"]["away"],
            "home_ht":       m["score"]["halfTime"]["home"],
            "away_ht":       m["score"]["halfTime"]["away"],
            "status":        m["status"],
            "date":          m["utcDate"][:10],
            "time":          m["utcDate"][11:16],
            "venue":         m.get("venue", ""),
            "referee":       m.get("referees", [{}])[0].get("name", "") if m.get("referees") else "",
            "goals":         goals,
            "bookings":      bookings,
            "substitutions": subs,
            "home_lineup":   home_lineup,
            "away_lineup":   away_lineup,
        }
    except Exception as e:
        print(f"Match detail error: {e}")
        return None

# ROUTES
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/match/<int:match_id>")
def match_page(match_id):
    return render_template("index.html")

@app.route("/api/matches/<league_code>")
def matches(league_code):
    now = time.time()
    if now - _matches_cache["timestamp"] < CACHE_TTL and league_code in _matches_cache["data"]:
        return jsonify(_matches_cache["data"][league_code])
    data = fetch_matches(league_code)
    _matches_cache["data"][league_code] = data
    _matches_cache["timestamp"] = now
    return jsonify(data)

@app.route("/api/standings/<league_code>")
def standings(league_code):
    now = time.time()
    if now - _standings_cache["timestamp"] < CACHE_TTL and league_code in _standings_cache["data"]:
        return jsonify(_standings_cache["data"][league_code])
    data = fetch_standings(league_code)
    _standings_cache["data"][league_code] = data
    _standings_cache["timestamp"] = now
    return jsonify(data)

@app.route("/api/sentiment/<subreddit>")
def sentiment(subreddit):
    if subreddit not in REDDIT_SUBS:
        return jsonify([])
    return jsonify(fetch_reddit_sentiment(subreddit))

@app.route("/api/match/<int:match_id>")
def match_detail(match_id):
    data = fetch_match_detail(match_id)
    if data is None:
        return jsonify({"error": "Match not found"}), 404
    return jsonify(data)

@app.route("/api/leagues")
def leagues():
    return jsonify(LEAGUES)

if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5001)