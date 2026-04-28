from flask import Flask, jsonify, render_template
from flask_cors import CORS
import requests
import sqlite3
import time
import os
import threading
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

# CONFIG
FOOTBALL_API_KEY = os.getenv("FOOTBALL_API_KEY", "")
FOOTBALL_BASE    = "https://api.football-data.org/v4"
REDDIT_BASE      = "https://www.reddit.com"

LEAGUES = {
    "PL":  {"name": "Premier League",    "flag": "🏴󠁧󠁢󠁥󠁮󠁧󠁿"},
    "PD":  {"name": "La Liga",           "flag": "🇪🇸"},
    "CL":  {"name": "Champions League",  "flag": "🏆"},
    "BL1": {"name": "Bundesliga",        "flag": "🇩🇪"},
    "SA":  {"name": "Serie A",           "flag": "🇮🇹"},
    "WC":  {"name": "World Cup",         "flag": "🌍"},
    "ELC": {"name": "Egyptian Premier League", "flag": "🇪🇬"},
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

# ANALYSIS
POSITIVE_WORDS = set([
    "win","won","goal","great","amazing","brilliant","excellent","fantastic",
    "superb","outstanding","perfect","best","love","incredible","awesome",
    "champion","trophy","legend","top","class","quality","clinical","dominated",
    "thrashed","hammered","destroyed","masterclass","unreal","fire"
])
NEGATIVE_WORDS = set([
    "loss","lost","terrible","awful","worst","poor","bad","disappointing",
    "disaster","pathetic","embarrassing","shocking","useless","rubbish","trash",
    "sacked","relegated","crisis","failed","embarrassment","joke","clown"
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

# Cache so we don't hammer the APIs on every request
_matches_cache = {"data": {}, "timestamp": 0}
_standings_cache = {"data": {}, "timestamp": 0}
CACHE_TTL = 300  # 5 minutes feels reasonable for live scores

def fetch_matches(league_code):
    headers = {"X-Auth-Token": FOOTBALL_API_KEY}
    try:
        res = requests.get(
            f"{FOOTBALL_BASE}/competitions/{league_code}/matches",
            params={"status": "LIVE,FINISHED,SCHEDULED", "limit": 10},
            headers=headers, timeout=10
        )
        if res.status_code != 200:
            return []
        data = res.json()
        matches = []
        for m in data.get("matches", [])[:10]:
            matches.append({
                "id": m["id"],
                "home": m["homeTeam"]["shortName"],
                "away": m["awayTeam"]["shortName"],
                "home_score": m["score"]["fullTime"]["home"],
                "away_score": m["score"]["fullTime"]["away"],
                "status": m["status"],
                "date": m["utcDate"][:10],
                "time": m["utcDate"][11:16],
            })
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
            return []
        data = res.json()
        table = data.get("standings", [{}])[0].get("table", [])
        return [{
            "pos": t["position"],
            "team": t["team"]["shortName"],
            "played": t["playedGames"],
            "won": t["won"],
            "draw": t["draw"],
            "lost": t["lost"],
            "points": t["points"],
            "gd": t["goalDifference"],
        } for t in table[:10]]
    except Exception as e:
        print(f"Standings error: {e}")
        return []

def fetch_reddit_sentiment(subreddit):
    # Scrape Reddit's public JSON endpoint
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
            title = d.get("title", "")
            score = d.get("score", 0)
            sentiment, s_score = analyze_sentiment(title)
            results.append({
                "title": title[:120],
                "score": score,
                "sentiment": sentiment,
                "sentiment_score": s_score,
                "url": f"https://reddit.com{d.get('permalink', '')}"
            })
        return results
    except Exception as e:
        print(f"Reddit error: {e}")
        return []

# ROUTES
@app.route("/")
def index():
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

@app.route("/api/leagues")
def leagues():
    return jsonify(LEAGUES)

if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5001)