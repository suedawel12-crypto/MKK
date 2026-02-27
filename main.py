import os
import sys
import logging
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

print("=" * 60)
print("🚀 STARTING BINGO BOT APPLICATION")
print("=" * 60)

# Import configuration
try:
    from config import settings
    print("✅ Config loaded successfully")
except Exception as e:
    print(f"❌ Failed to load config: {e}")
    sys.exit(1)

# Import database
try:
    from database import get_db, init_db, User, Room, Round, Card, Transaction
    print("✅ Database module loaded")
except Exception as e:
    print(f"❌ Failed to load database: {e}")
    sys.exit(1)

# Import bot
try:
    from bot import bingo_bot
    print("✅ Bot module loaded")
except Exception as e:
    print(f"❌ Failed to load bot: {e}")
    # Don't exit, allow app to start for debugging
    bingo_bot = None

# Import Redis
try:
    from redis_client import redis_client
    print("✅ Redis module loaded")
except Exception as e:
    print(f"❌ Failed to load redis: {e}")
    redis_client = None

# Import admin (optional)
try:
    from admin import router as admin_router
    print("✅ Admin module loaded")
except Exception as e:
    print(f"❌ Failed to load admin: {e}")
    admin_router = None

# Create FastAPI app
app = FastAPI(title="Bingo Bot", version="1.0.0")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Templates
templates = Jinja2Templates(directory="templates")

# Include routers
if admin_router:
    app.include_router(admin_router)

@app.on_event("startup")
async def startup_event():
    """Initialize services on startup"""
    logger.info("🚀 Application starting up...")
    
    try:
        # Initialize database
        init_db()
        logger.info("✅ Database initialized")
    except Exception as e:
        logger.error(f"❌ Database initialization failed: {e}")
    
    try:
        # Connect to Redis
        if redis_client:
            await redis_client.connect()
            logger.info("✅ Redis connected")
    except Exception as e:
        logger.error(f"❌ Redis connection failed: {e}")
    
    try:
        # Set webhook for bot
        if bingo_bot:
            await bingo_bot.set_webhook()
            logger.info("✅ Bot webhook set")
    except Exception as e:
        logger.error(f"❌ Bot webhook setup failed: {e}")
    
    logger.info("✅ Startup complete!")

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    logger.info("🛑 Application shutting down...")

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "status": "running",
        "app": "Bingo Bot",
        "environment": settings.ENVIRONMENT,
        "time": datetime.utcnow().isoformat(),
        "bot_configured": bingo_bot is not None,
        "database_configured": settings.DATABASE_URL is not None,
        "redis_configured": settings.REDIS_URL is not None
    }

@app.get("/health")
async def health():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.post("/webhook")
async def telegram_webhook(request: Request):
    """Telegram webhook endpoint"""
    try:
        data = await request.json()
        logger.info(f"📩 Received webhook update: {data.get('update_id', 'unknown')}")
        
        if bingo_bot:
            await bingo_bot.app.process_update(data)
            return {"ok": True, "status": "processed"}
        else:
            logger.error("Bot not initialized")
            return {"ok": False, "error": "Bot not initialized"}
    
    except Exception as e:
        logger.error(f"❌ Webhook error: {e}")
        return {"ok": False, "error": str(e)}

@app.get("/webapp", response_class=HTMLResponse)
async def webapp(request: Request):
    """Serve the WebApp"""
    return templates.TemplateResponse("webapp.html", {"request": request})

@app.get("/admin", response_class=HTMLResponse)
async def admin_panel(request: Request):
    """Serve admin panel"""
    return templates.TemplateResponse("admin.html", {"request": request})

@app.get("/test")
async def test():
    """Simple test endpoint"""
    return {
        "message": "Server is running!",
        "time": datetime.utcnow().isoformat(),
        "env": settings.ENVIRONMENT
    }

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    logger.info(f"Starting server on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)