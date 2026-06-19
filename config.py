"""
Configuration Management for Free Fire Like Bot API
Load all settings from environment variables
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ==================== API Configuration ====================
PORT = int(os.environ.get("PORT", 10000))
DEBUG = os.environ.get("DEBUG", "False").lower() == "true"

# ==================== Telegram Bot Configuration ====================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
ADMIN_ID = os.environ.get("ADMIN_ID")
API_URL = os.environ.get("API_URL", f"http://localhost:{PORT}")

if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN is required!")
if not ADMIN_ID:
    raise ValueError("ADMIN_ID is required!")

# ==================== Server Configuration ====================
SERVERS = {
    "EUROPE": os.getenv("EUROPE_SERVER", "https://clientbp.ggblueshark.com"),
    "IND": os.getenv("IND_SERVER", "https://client.ind.freefiremobile.com"),
    "BR": os.getenv("BR_SERVER", "https://client.us.freefiremobile.com"),
}

# ==================== Token Manager Configuration ====================
AUTH_URL = os.environ.get("AUTH_URL", "https://jwtxthug.up.railway.app/token")
CACHE_DURATION = 7 * 3600  # 7 hours in seconds
TOKEN_REFRESH_THRESHOLD = 6 * 3600  # 6 hours in seconds

# ==================== Scheduler Configuration ====================
HORARIO_ENVIO = os.environ.get("HORARIO_ENVIO", "13:00")
INTERVALO_RETENTATIVA = int(os.environ.get("INTERVALO_RETENTATIVA", 2))  # hours
TIMEZONE = os.environ.get("TIMEZONE", "America/Sao_Paulo")

# ==================== Database Configuration ====================
DATABASE_PATH = os.environ.get("DATABASE_PATH", "likes_bot.db")

# ==================== Logging Configuration ====================
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
LOG_FILE = os.environ.get("LOG_FILE", "app.log")
