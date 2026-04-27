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
    "EPL": {"name": "Egyptian Premier League", "flag": " "},
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