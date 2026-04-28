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