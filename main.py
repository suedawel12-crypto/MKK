from fastapi import FastAPI, Request, HTTPException, Depends, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
import logging
import json
from datetime import datetime

from database import get_db, init_db, User, Room, Round, Card, Transaction, AuditLog
from bot import bingo_bot
from redis_client import redis_client
from websocket import ws_handler, manager
from workers import round_worker, claim_processor
from security import security_manager, FraudDetector
from config import settings

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI
app = FastAPI(title="Bingo 75 Enterprise")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Templates
templates = Jinja2Templates(directory="templates")

# Initialize database on startup
@app.on_event("startup")
async def startup():
    # Initialize database
    init_db()
    
    # Connect to Redis
    await redis_client.connect()
    
    # Set webhook for bot
    await bingo_bot.set_webhook()
    
    # Start round worker
    await round_worker.start()
    
    logger.info("Application started")

@app.on_event("shutdown")
async def shutdown():
    await round_worker.stop()
    logger.info("Application shutdown")

# Health check
@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

# Telegram webhook
@app.post("/webhook")
async def telegram_webhook(request: Request):
    """Handle Telegram updates"""
    update_data = await request.json()
    await bingo_bot.app.process_update(update_data)
    return {"ok": True}

# WebApp interface
@app.get("/webapp", response_class=HTMLResponse)
async def webapp(request: Request):
    """Serve the WebApp"""
    return templates.TemplateResponse("webapp.html", {"request": request})

# WebSocket connection
@app.websocket("/ws/{room_id}/{user_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: int, user_id: int):
    await ws_handler.handle_connection(websocket, room_id, user_id)

# API Routes
@app.post("/api/buy_card")
async def buy_card(
    request: Request,
    db: Session = Depends(get_db)
):
    """Buy a card for current round"""
    data = await request.json()
    init_data = request.headers.get("X-Telegram-Init-Data")
    
    # Verify Telegram data
    if not security_manager.verify_telegram_init_data(init_data):
        raise HTTPException(status_code=401, detail="Invalid initialization data")
    
    user_id = data.get("user_id")
    round_id = data.get("round_id")
    
    # Get user and round
    user = db.query(User).filter(User.telegram_id == str(user_id)).first()
    if not user or user.is_blocked:
        raise HTTPException(status_code=403, detail="User not found or blocked")
    
    round = db.query(Round).filter(Round.id == round_id, Round.status == 'waiting').first()
    if not round:
        raise HTTPException(status_code=400, detail="Round not available")
    
    room = db.query(Room).filter(Room.id == round.room_id).first()
    
    # Check balance
    if user.wallet_balance < room.card_price:
        raise HTTPException(status_code=400, detail="Insufficient balance")
    
    # Check rate limit
    rate_key = f"buy:{user_id}"
    if not await redis_client.check_rate_limit(rate_key, 5, 60):
        raise HTTPException(status_code=429, detail="Too many requests")
    
    # Generate random card (75-ball: 3 rows, 5 numbers per row)
    numbers = []
    available = list(range(1, 76))
    for _ in range(3):
        row = []
        for _ in range(5):
            if available:
                num = random.SystemRandom().choice(available)
                available.remove(num)
                row.append(num)
        numbers.append(sorted(row))
    
    # Create card
    card = Card(
        round_id=round_id,
        user_id=user.id,
        numbers=numbers
    )
    db.add(card)
    
    # Deduct balance
    user.wallet_balance -= room.card_price
    
    # Update round pool
    round.total_pool += room.card_price
    
    # Create transaction
    transaction = Transaction(
        user_id=user.id,
        amount=-room.card_price,
        type="buy_card"
    )
    db.add(transaction)
    
    # Audit log
    audit = AuditLog(
        action="buy_card",
        user_id=user.id,
        details={"round_id": round_id, "price": room.card_price}
    )
    db.add(audit)
    
    db.commit()
    
    return {
        "success": True,
        "card_id": card.id,
        "numbers": numbers,
        "balance": user.wallet_balance
    }

@app.post("/api/claim")
async def claim_win(
    request: Request,
    db: Session = Depends(get_db)
):
    """Claim a win"""
    data = await request.json()
    init_data = request.headers.get("X-Telegram-Init-Data")
    
    # Verify Telegram data
    if not security_manager.verify_telegram_init_data(init_data):
        raise HTTPException(status_code=401, detail="Invalid initialization data")
    
    user_id = data.get("user_id")
    round_id = data.get("round_id")
    card_id = data.get("card_id")
    
    # Get user
    user = db.query(User).filter(User.telegram_id == str(user_id)).first()
    if not user or user.is_blocked:
        raise HTTPException(status_code=403, detail="User not found or blocked")
    
    # Check rate limit
    rate_key = f"claim:{user_id}"
    if not await redis_client.check_rate_limit(rate_key, 3, 60):
        raise HTTPException(status_code=429, detail="Too many claims")
    
    # Process claim
    result = await claim_processor.process_claim(round_id, card_id, user.id, db)
    
    if not result['success']:
        raise HTTPException(status_code=400, detail=result['message'])
    
    return result

@app.get("/api/round/{room_id}")
async def get_current_round(room_id: int, db: Session = Depends(get_db)):
    """Get current round info"""
    round = db.query(Round).filter(
        Round.room_id == room_id,
        Round.status.in_(['waiting', 'active'])
    ).order_by(Round.created_at.desc()).first()
    
    if not round:
        return {"status": "no_round"}
    
    # Get user cards for this round (if any)
    # This would need user_id from query params
    
    return {
        "round_id": round.id,
        "status": round.status,
        "total_pool": round.total_pool,
        "jackpot_pool": round.jackpot_pool,
        "numbers_called": round.numbers_called,
        "start_time": round.start_time,
        "card_price": round.room.card_price if round.room else 0
    }

# Admin routes
@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    """Admin dashboard"""
    return templates.TemplateResponse("admin.html", {"request": request})

@app.get("/api/admin/stats")
async def admin_stats(
    request: Request,
    db: Session = Depends(get_db)
):
    """Get admin stats"""
    # Verify admin (would need proper auth)
    admin_id = request.headers.get("X-Admin-ID")
    if int(admin_id) not in settings.ADMIN_IDS:
        raise HTTPException(status_code=403, detail="Unauthorized")
    
    # Get stats
    total_users = db.query(User).count()
    active_rounds = db.query(Round).filter(Round.status == 'active').count()
    total_volume = db.query(Transaction).filter(Transaction.type == 'buy_card').count()
    total_winnings = db.query(Transaction).filter(
        Transaction.type.in_(['win', 'jackpot'])
    ).with_entities(func.sum(Transaction.amount)).scalar() or 0
    
    return {
        "total_users": total_users,
        "active_rounds": active_rounds,
        "total_volume": total_volume,
        "total_winnings": total_winnings,
        "recent_transactions": []
    }

@app.post("/api/admin/block_user/{user_id}")
async def block_user(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Block/unblock user"""
    # Verify admin
    admin_id = request.headers.get("X-Admin-ID")
    if int(admin_id) not in settings.ADMIN_IDS:
        raise HTTPException(status_code=403, detail="Unauthorized")
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    user.is_blocked = not user.is_blocked
    db.commit()
    
    return {"success": True, "blocked": user.is_blocked}

# Payment webhook
@app.post("/api/payment/webhook")
async def payment_webhook(request: Request, db: Session = Depends(get_db)):
    """Handle payment provider webhook"""
    data = await request.json()
    
    # Verify payment signature (implementation depends on provider)
    
    user_id = data.get("user_id")
    amount = data.get("amount")
    tx_id = data.get("transaction_id")
    
    # Credit user
    user = db.query(User).filter(User.telegram_id == str(user_id)).first()
    if user:
        user.wallet_balance += amount
        
        transaction = Transaction(
            user_id=user.id,
            amount=amount,
            type="deposit",
            reference_id=tx_id
        )
        db.add(transaction)
        db.commit()
        
        # Notify user via bot
        await bingo_bot.app.bot.send_message(
            user_id,
            f"💰 Deposit of ${amount} successful! New balance: ${user.wallet_balance:.2f}"
        )
    
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)