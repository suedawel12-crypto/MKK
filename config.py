import os
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()

class Settings(BaseSettings):
    # App
    APP_NAME: str = "Bingo 75 Enterprise"
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "production")
    SECRET_KEY: str = os.getenv("SECRET_KEY", "9fc35a300e1331d52d4832176be564767377d10be933cb857de8735ed4de8401")
    
    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    
    # Redis
    REDIS_URL: str = os.getenv("REDIS_URL", "")
    
    # Telegram
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "8509514963:AAGbedUD8Zup0c4oGZ9v3Qlo2IyQYPArIA")
    WEBHOOK_URL: str = os.getenv("WEBHOOK_URL", "https://mkk-production.up.railway.app")
    ADMIN_IDS: list = [int(id) for id in os.getenv("ADMIN_IDS", "8741250511").split(",") if id]
    
    # Bingo Settings
    NUMBER_CALL_INTERVAL: int = int(os.getenv("NUMBER_CALL_INTERVAL", "5"))
    ROUND_DELAY: int = int(os.getenv("ROUND_DELAY", "10"))
    HOUSE_COMMISSION: float = 0.20
    WINNER_COMMISSION: float = 0.70
    JACKPOT_COMMISSION: float = 0.10
    JACKPOT_THRESHOLD: int = int(os.getenv("JACKPOT_THRESHOLD", "40"))
    
    # Security
    RATE_LIMIT_CALLS: int = int(os.getenv("RATE_LIMIT_CALLS", "10"))
    RATE_LIMIT_PERIOD: int = int(os.getenv("RATE_LIMIT_PERIOD", "60"))
    MAX_CARDS_PER_USER: int = 10
    
    # Payment (Optional)
    STRIPE_SECRET_KEY: str = os.getenv("STRIPE_SECRET_KEY", "")
    STRIPE_WEBHOOK_SECRET: str = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    
    class Config:
        case_sensitive = True

settings = Settings()

# Print config on startup (without sensitive data)
print("=" * 50)
print("🚀 Bingo Bot Configuration")
print("=" * 50)
print(f"Environment: {settings.ENVIRONMENT}")
print(f"Webhook URL: {settings.WEBHOOK_URL}")
print(f"Bot Token: {settings.BOT_TOKEN[:10]}...{settings.BOT_TOKEN[-10:]}")
print(f"Admin IDs: {settings.ADMIN_IDS}")
print(f"Database: {'Set' if settings.DATABASE_URL else 'Not Set'}")
print(f"Redis: {'Set' if settings.REDIS_URL else 'Not Set'}")
print("=" * 50)