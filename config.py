import os
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()

class Settings(BaseSettings):
    # App
    APP_NAME: str = "Bingo 75 Enterprise"
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "production")
    SECRET_KEY: str = os.getenv("SECRET_KEY", "your-secret-key-change-in-prod")
    
    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql://postgres:password@localhost:5432/bingo")
    
    # Redis
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379")
    
    # Telegram
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    WEBHOOK_URL: str = os.getenv("WEBHOOK_URL", "")
    ADMIN_IDS: list = [int(id) for id in os.getenv("ADMIN_IDS", "").split(",") if id]
    
    # Bingo Settings
    NUMBER_CALL_INTERVAL: int = 5  # seconds
    ROUND_DELAY: int = 10  # seconds between rounds
    HOUSE_COMMISSION: float = 0.20  # 20%
    WINNER_COMMISSION: float = 0.70  # 70%
    JACKPOT_COMMISSION: float = 0.10  # 10%
    
    # Security
    RATE_LIMIT_CALLS: int = 10
    RATE_LIMIT_PERIOD: int = 60  # seconds
    MAX_CARDS_PER_USER: int = 10
    
    class Config:
        case_sensitive = True

settings = Settings()