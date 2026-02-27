import os
from typing import List, Optional
from dotenv import load_dotenv

load_dotenv()

class Settings:
    def __init__(self):
        # App
        self.APP_NAME: str = "Bingo 75 Enterprise"
        self.ENVIRONMENT: str = os.getenv("ENVIRONMENT", "production")
        self.SECRET_KEY: str = os.getenv("SECRET_KEY", "9fc35a300e1331d52d4832176be564767377d10be933cb857de8735ed4de8401")
        
        # Database
        self.DATABASE_URL: str = os.getenv("DATABASE_URL", "")
        
        # Redis
        self.REDIS_URL: str = os.getenv("REDIS_URL", "")
        
        # Telegram
        self.BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
        self.WEBHOOK_URL: str = os.getenv("WEBHOOK_URL", "https://mkk-production.up.railway.app")
        
        # ADMIN_IDS - Parse from string (FIXED)
        admin_ids_str = os.getenv("ADMIN_IDS", "8741250511")
        self.ADMIN_IDS: List[int] = []
        if admin_ids_str:
            try:
                # Handle comma-separated list or single value
                if "," in admin_ids_str:
                    self.ADMIN_IDS = [int(id.strip()) for id in admin_ids_str.split(",") if id.strip()]
                else:
                    self.ADMIN_IDS = [int(admin_ids_str)]
            except ValueError as e:
                print(f"⚠️ Warning: Could not parse ADMIN_IDS '{admin_ids_str}': {e}")
                self.ADMIN_IDS = []
        
        # Bingo Settings
        self.NUMBER_CALL_INTERVAL: int = int(os.getenv("NUMBER_CALL_INTERVAL", "5"))
        self.ROUND_DELAY: int = int(os.getenv("ROUND_DELAY", "10"))
        self.HOUSE_COMMISSION: float = 0.20
        self.WINNER_COMMISSION: float = 0.70
        self.JACKPOT_COMMISSION: float = 0.10
        self.JACKPOT_THRESHOLD: int = int(os.getenv("JACKPOT_THRESHOLD", "40"))
        
        # Security
        self.RATE_LIMIT_CALLS: int = int(os.getenv("RATE_LIMIT_CALLS", "10"))
        self.RATE_LIMIT_PERIOD: int = int(os.getenv("RATE_LIMIT_PERIOD", "60"))
        self.MAX_CARDS_PER_USER: int = 10
        
        # Payment (Optional)
        self.STRIPE_SECRET_KEY: str = os.getenv("STRIPE_SECRET_KEY", "")
        self.STRIPE_WEBHOOK_SECRET: str = os.getenv("STRIPE_WEBHOOK_SECRET", "")

# Create global settings instance
settings = Settings()

# Print configuration on startup
print("=" * 60)
print("🚀 BINGO BOT CONFIGURATION")
print("=" * 60)
print(f"Environment: {settings.ENVIRONMENT}")
print(f"Webhook URL: {settings.WEBHOOK_URL}")
print(f"Bot Token: {settings.BOT_TOKEN[:10]}...{settings.BOT_TOKEN[-10:] if len(settings.BOT_TOKEN) > 20 else ''}")
print(f"Admin IDs: {settings.ADMIN_IDS}")
print(f"Database: {'✅ Set' if settings.DATABASE_URL else '❌ Not Set'}")
print(f"Redis: {'✅ Set' if settings.REDIS_URL else '❌ Not Set'}")
print(f"Rate Limit: {settings.RATE_LIMIT_CALLS} calls per {settings.RATE_LIMIT_PERIOD}s")
print("=" * 60)