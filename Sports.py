from flask import Flask, jsonify, render_template
from flask_cors import CORS
import requests
import sqlite3
import time
import os
import threading
from datetime import datetime
 
app = Flask(__name__)
CORS(app)
 
# ── CONFIG ────────────────────────────────────────────────────────────────────
FOOTBALL_API_KEY = ""
FOOTBALL_BASE    = "https://api.football-data.org/v4"
REDDIT_BASE      = "https://www.reddit.com"