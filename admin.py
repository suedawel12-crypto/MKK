from fastapi import APIRouter, Request, HTTPException, Depends, Query
from fastapi.responses import JSONResponse, FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from datetime import datetime, timedelta
import csv
import io
import json
from typing import Optional

from database import get_db, User, Room, Round, Card, Transaction, AuditLog
from security import security_manager
from config import settings
from workers import round_worker

router = APIRouter(prefix="/api/admin", tags=["admin"])

# Admin authentication middleware
async def verify_admin(request: Request, db: Session = Depends(get_db)):
    """Verify admin access"""
    # Check admin ID header
    admin_id = request.headers.get("X-Admin-ID")
    admin_token = request.headers.get("X-Admin-Token")
    
    if not admin_id or int(admin_id) not in settings.ADMIN_IDS:
        # Check JWT token as alternative
        if admin_token:
            try:
                payload = security_manager.verify_jwt(admin_token)
                if payload.get("user_id") in settings.ADMIN_IDS:
                    return payload
            except:
                pass
        raise HTTPException(status_code=403, detail="Unauthorized access")
    
    return {"admin_id": int(admin_id)}

# ================ DASHBOARD STATS ================

@router.get("/stats")
async def get_admin_stats(
    admin=Depends(verify_admin),
    db: Session = Depends(get_db)
):
    """Get dashboard statistics"""
    # Total users
    total_users = db.query(User).count()
    active_users = db.query(User).filter(
        User.last_active >= datetime.utcnow() - timedelta(days=7)
    ).count()
    blocked_users = db.query(User).filter(User.is_blocked == True).count()
    
    # Rounds stats
    active_rounds = db.query(Round).filter(Round.status == 'active').count()
    waiting_rounds = db.query(Round).filter(Round.status == 'waiting').count()
    completed_rounds = db.query(Round).filter(Round.status == 'completed').count()
    jackpot_rounds = db.query(Round).filter(Round.status == 'jackpot').count()
    
    # Financial stats
    total_cards_sold = db.query(Card).count()
    
    total_deposits = db.query(func.sum(Transaction.amount)).filter(
        Transaction.type == 'deposit',
        Transaction.status == 'completed'
    ).scalar() or 0
    
    total_withdrawals = db.query(func.sum(Transaction.amount)).filter(
        Transaction.type == 'withdrawal',
        Transaction.status == 'completed'
    ).scalar() or 0
    
    total_winnings = db.query(func.sum(Transaction.amount)).filter(
        Transaction.type.in_(['win', 'jackpot']),
        Transaction.status == 'completed'
    ).scalar() or 0
    
    # House profit (commission)
    house_profit = total_deposits - total_winnings
    
    # Recent revenue data for chart (last 7 days)
    revenue_data = []
    labels = []
    for i in range(6, -1, -1):
        date = datetime.utcnow().date() - timedelta(days=i)
        labels.append(date.strftime("%Y-%m-%d"))
        
        day_revenue = db.query(func.sum(Transaction.amount)).filter(
            Transaction.type == 'deposit',
            Transaction.status == 'completed',
            func.date(Transaction.timestamp) == date
        ).scalar() or 0
        
        revenue_data.append(float(day_revenue))
    
    return {
        "total_users": total_users,
        "active_users": active_users,
        "blocked_users": blocked_users,
        "active_rounds": active_rounds,
        "waiting_rounds": waiting_rounds,
        "completed_rounds": completed_rounds,
        "jackpot_rounds": jackpot_rounds,
        "total_cards_sold": total_cards_sold,
        "total_deposits": float(total_deposits),
        "total_withdrawals": float(total_withdrawals),
        "total_winnings": float(total_winnings),
        "house_profit": float(house_profit),
        "revenue_data": {
            "labels": labels,
            "values": revenue_data
        }
    }

# ================ ROOM MANAGEMENT ================

@router.get("/rooms")
async def get_rooms(
    admin=Depends(verify_admin),
    db: Session = Depends(get_db)
):
    """Get all rooms with current stats"""
    rooms = db.query(Room).all()
    result = []
    
    for room in rooms:
        # Get current active round
        current_round = db.query(Round).filter(
            Round.room_id == room.id,
            Round.status.in_(['waiting', 'active'])
        ).first()
        
        # Get player count in current round
        players = 0
        if current_round:
            players = db.query(Card).filter(
                Card.round_id == current_round.id
            ).distinct(Card.user_id).count()
        
        result.append({
            "id": room.id,
            "name": room.name,
            "description": room.description,
            "card_price": float(room.card_price),
            "max_players": room.max_players,
            "status": room.status,
            "players": players,
            "current_round": current_round.id if current_round else None,
            "created_at": room.created_at.isoformat() if room.created_at else None
        })
    
    return result

@router.post("/rooms")
async def create_room(
    request: Request,
    admin=Depends(verify_admin),
    db: Session = Depends(get_db)
):
    """Create a new room"""
    data = await request.json()
    
    room = Room(
        name=data.get("name"),
        description=data.get("description", ""),
        card_price=float(data.get("price", 1.0)),
        max_players=int(data.get("max_players", 100)),
        status="active"
    )
    
    db.add(room)
    db.commit()
    db.refresh(room)
    
    # Create initial round for room
    new_round = Round(
        room_id=room.id,
        status="waiting",
        numbers_called=[]
    )
    db.add(new_round)
    db.commit()
    
    # Audit log
    audit = AuditLog(
        action="create_room",
        user_id=admin.get("admin_id"),
        details={"room_id": room.id, "name": room.name}
    )
    db.add(audit)
    db.commit()
    
    return {"success": True, "room_id": room.id}

@router.put("/rooms/{room_id}")
async def update_room(
    room_id: int,
    request: Request,
    admin=Depends(verify_admin),
    db: Session = Depends(get_db)
):
    """Update room settings"""
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    
    data = await request.json()
    
    if "name" in data:
        room.name = data["name"]
    if "description" in data:
        room.description = data["description"]
    if "price" in data:
        room.card_price = float(data["price"])
    if "max_players" in data:
        room.max_players = int(data["max_players"])
    if "status" in data:
        room.status = data["status"]
    
    db.commit()
    
    # Audit log
    audit = AuditLog(
        action="update_room",
        user_id=admin.get("admin_id"),
        details={"room_id": room_id, "changes": data}
    )
    db.add(audit)
    db.commit()
    
    return {"success": True}

@router.delete("/rooms/{room_id}")
async def delete_room(
    room_id: int,
    admin=Depends(verify_admin),
    db: Session = Depends(get_db)
):
    """Delete a room (soft delete by setting inactive)"""
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    
    room.status = "deleted"
    db.commit()
    
    # Audit log
    audit = AuditLog(
        action="delete_room",
        user_id=admin.get("admin_id"),
        details={"room_id": room_id}
    )
    db.add(audit)
    db.commit()
    
    return {"success": True}

# ================ ROUND MANAGEMENT ================

@router.get("/rounds")
async def get_rounds(
    status: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    admin=Depends(verify_admin),
    db: Session = Depends(get_db)
):
    """Get all rounds with filters"""
    query = db.query(Round).join(Room).order_by(desc(Round.created_at))
    
    if status:
        query = query.filter(Round.status == status)
    
    rounds = query.limit(limit).all()
    result = []
    
    for round in rounds:
        # Get winner info
        winner = None
        if round.winner_id:
            winner_user = db.query(User).filter(User.id == round.winner_id).first()
            if winner_user:
                winner = {
                    "id": winner_user.id,
                    "username": winner_user.username,
                    "telegram_id": winner_user.telegram_id
                }
        
        result.append({
            "id": round.id,
            "room_id": round.room_id,
            "room_name": round.room.name if round.room else "Unknown",
            "status": round.status,
            "total_pool": float(round.total_pool),
            "jackpot_pool": float(round.jackpot_pool),
            "numbers_called": round.numbers_called,
            "numbers_count": len(round.numbers_called) if round.numbers_called else 0,
            "winner": winner,
            "winner_amount": float(round.winner_amount) if round.winner_amount else 0,
            "start_time": round.start_time.isoformat() if round.start_time else None,
            "end_time": round.end_time.isoformat() if round.end_time else None,
            "created_at": round.created_at.isoformat() if round.created_at else None
        })
    
    return result

@router.post("/rounds/{round_id}/call")
async def force_call_number(
    round_id: int,
    admin=Depends(verify_admin),
    db: Session = Depends(get_db)
):
    """Force call a number in a round"""
    round = db.query(Round).filter(Round.id == round_id).first()
    if not round:
        raise HTTPException(status_code=404, detail="Round not found")
    
    if round.status != 'active':
        raise HTTPException(status_code=400, detail="Round is not active")
    
    # Get available numbers
    called = set(round.numbers_called or [])
    available = [n for n in range(1, 76) if n not in called]
    
    if not available:
        raise HTTPException(status_code=400, detail="All numbers have been called")
    
    # Call random number
    import random
    number = random.SystemRandom().choice(available)
    
    # Update round
    round.numbers_called = list(called) + [number]
    db.commit()
    
    # Broadcast via Redis
    from redis_client import redis_client
    await redis_client.publish(f"room:{round.room_id}", {
        'type': 'number_called',
        'round_id': round.id,
        'number': number,
        'called_numbers': round.numbers_called
    })
    
    # Audit log
    audit = AuditLog(
        action="force_call_number",
        user_id=admin.get("admin_id"),
        details={"round_id": round_id, "number": number}
    )
    db.add(audit)
    db.commit()
    
    return {"success": True, "number": number}

@router.post("/rounds/{round_id}/end")
async def end_round_early(
    round_id: int,
    admin=Depends(verify_admin),
    db: Session = Depends(get_db)
):
    """End a round early (no winner)"""
    round = db.query(Round).filter(Round.id == round_id).first()
    if not round:
        raise HTTPException(status_code=404, detail="Round not found")
    
    round.status = 'completed'
    round.end_time = datetime.utcnow()
    db.commit()
    
    # Broadcast round end
    from redis_client import redis_client
    await redis_client.publish(f"room:{round.room_id}", {
        'type': 'round_ended',
        'round_id': round.id
    })
    
    # Create next round
    new_round = Round(
        room_id=round.room_id,
        status='waiting',
        numbers_called=[]
    )
    db.add(new_round)
    db.commit()
    
    # Audit log
    audit = AuditLog(
        action="end_round_early",
        user_id=admin.get("admin_id"),
        details={"round_id": round_id}
    )
    db.add(audit)
    db.commit()
    
    return {"success": True}

# ================ USER MANAGEMENT ================

@router.get("/users")
async def get_users(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    search: Optional[str] = None,
    admin=Depends(verify_admin),
    db: Session = Depends(get_db)
):
    """Get users with pagination and search"""
    query = db.query(User)
    
    if search:
        query = query.filter(
            (User.username.ilike(f"%{search}%")) |
            (User.telegram_id.ilike(f"%{search}%")) |
            (User.first_name.ilike(f"%{search}%")) |
            (User.last_name.ilike(f"%{search}%"))
        )
    
    total = query.count()
    users = query.order_by(desc(User.created_at)).offset((page - 1) * limit).limit(limit).all()
    
    result = []
    for user in users:
        # Get user stats
        total_cards = db.query(Card).filter(Card.user_id == user.id).count()
        total_wins = db.query(Round).filter(Round.winner_id == user.id).count()
        total_spent = db.query(func.sum(Transaction.amount)).filter(
            Transaction.user_id == user.id,
            Transaction.type == 'buy_card',
            Transaction.status == 'completed'
        ).scalar() or 0
        
        total_won = db.query(func.sum(Transaction.amount)).filter(
            Transaction.user_id == user.id,
            Transaction.type.in_(['win', 'jackpot']),
            Transaction.status == 'completed'
        ).scalar() or 0
        
        result.append({
            "id": user.id,
            "telegram_id": user.telegram_id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "wallet_balance": float(user.wallet_balance),
            "is_blocked": user.is_blocked,
            "is_admin": user.is_admin,
            "total_cards": total_cards,
            "total_wins": total_wins,
            "total_spent": float(abs(total_spent)) if total_spent else 0,
            "total_won": float(total_won) if total_won else 0,
            "net_profit": float(total_won - abs(total_spent)) if total_spent and total_won else 0,
            "ip_addresses": user.ip_addresses,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "last_active": user.last_active.isoformat() if user.last_active else None
        })
    
    return {
        "total": total,
        "page": page,
        "limit": limit,
        "users": result
    }

@router.get("/users/{user_id}")
async def get_user_details(
    user_id: int,
    admin=Depends(verify_admin),
    db: Session = Depends(get_db)
):
    """Get detailed user information"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Get recent transactions
    transactions = db.query(Transaction).filter(
        Transaction.user_id == user.id
    ).order_by(desc(Transaction.timestamp)).limit(20).all()
    
    # Get recent rounds
    rounds = db.query(Round).filter(
        Round.winner_id == user.id
    ).order_by(desc(Round.end_time)).limit(10).all()
    
    # Get audit logs
    audit_logs = db.query(AuditLog).filter(
        AuditLog.user_id == user.id
    ).order_by(desc(AuditLog.timestamp)).limit(20).all()
    
    return {
        "user": {
            "id": user.id,
            "telegram_id": user.telegram_id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "wallet_balance": float(user.wallet_balance),
            "is_blocked": user.is_blocked,
            "is_admin": user.is_admin,
            "ip_addresses": user.ip_addresses,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "last_active": user.last_active.isoformat() if user.last_active else None
        },
        "transactions": [
            {
                "id": t.id,
                "amount": float(t.amount),
                "type": t.type,
                "reference_id": t.reference_id,
                "status": t.status,
                "timestamp": t.timestamp.isoformat() if t.timestamp else None
            } for t in transactions
        ],
        "wins": [
            {
                "round_id": r.id,
                "amount": float(r.winner_amount) if r.winner_amount else 0,
                "numbers_called": len(r.numbers_called) if r.numbers_called else 0,
                "date": r.end_time.isoformat() if r.end_time else None
            } for r in rounds
        ],
        "audit_logs": [
            {
                "action": log.action,
                "details": log.details,
                "ip_address": log.ip_address,
                "timestamp": log.timestamp.isoformat() if log.timestamp else None
            } for log in audit_logs
        ]
    }

@router.post("/users/{user_id}/block")
async def toggle_user_block(
    user_id: int,
    admin=Depends(verify_admin),
    db: Session = Depends(get_db)
):
    """Block or unblock a user"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    user.is_blocked = not user.is_blocked
    db.commit()
    
    # Audit log
    audit = AuditLog(
        action="toggle_block" if user.is_blocked else "toggle_unblock",
        user_id=admin.get("admin_id"),
        details={"target_user_id": user_id, "blocked": user.is_blocked}
    )
    db.add(audit)
    db.commit()
    
    return {"success": True, "blocked": user.is_blocked}

@router.post("/users/{user_id}/adjust-balance")
async def adjust_user_balance(
    user_id: int,
    request: Request,
    admin=Depends(verify_admin),
    db: Session = Depends(get_db)
):
    """Manually adjust user balance"""
    data = await request.json()
    amount = float(data.get("amount", 0))
    reason = data.get("reason", "Manual adjustment")
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    user.wallet_balance += amount
    
    transaction = Transaction(
        user_id=user.id,
        amount=amount,
        type="adjustment",
        reference_id=f"admin_{admin.get('admin_id')}"
    )
    db.add(transaction)
    db.commit()
    
    # Audit log
    audit = AuditLog(
        action="balance_adjustment",
        user_id=admin.get("admin_id"),
        details={
            "target_user_id": user_id,
            "amount": amount,
            "reason": reason,
            "new_balance": float(user.wallet_balance)
        }
    )
    db.add(audit)
    db.commit()
    
    return {"success": True, "new_balance": float(user.wallet_balance)}

# ================ TRANSACTIONS ================

@router.get("/transactions")
async def get_transactions(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    type: Optional[str] = None,
    user_id: Optional[int] = None,
    admin=Depends(verify_admin),
    db: Session = Depends(get_db)
):
    """Get all transactions with filters"""
    query = db.query(Transaction).join(User).order_by(desc(Transaction.timestamp))
    
    if type:
        query = query.filter(Transaction.type == type)
    
    if user_id:
        query = query.filter(Transaction.user_id == user_id)
    
    total = query.count()
    transactions = query.offset((page - 1) * limit).limit(limit).all()
    
    result = []
    for tx in transactions:
        result.append({
            "id": tx.id,
            "user_id": tx.user_id,
            "username": tx.user.username if tx.user else "Unknown",
            "amount": float(tx.amount),
            "type": tx.type,
            "reference_id": tx.reference_id,
            "status": tx.status,
            "timestamp": tx.timestamp.isoformat() if tx.timestamp else None
        })
    
    return {
        "total": total,
        "page": page,
        "limit": limit,
        "transactions": result
    }

# ================ AUDIT LOGS ================

@router.get("/audit")
async def get_audit_logs(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    action: Optional[str] = None,
    user_id: Optional[int] = None,
    admin=Depends(verify_admin),
    db: Session = Depends(get_db)
):
    """Get audit logs with filters"""
    query = db.query(AuditLog).outerjoin(User).order_by(desc(AuditLog.timestamp))
    
    if action:
        query = query.filter(AuditLog.action == action)
    
    if user_id:
        query = query.filter(AuditLog.user_id == user_id)
    
    total = query.count()
    logs = query.offset((page - 1) * limit).limit(limit).all()
    
    result = []
    for log in logs:
        result.append({
            "id": log.id,
            "action": log.action,
            "user_id": log.user_id,
            "username": log.user.username if log.user else "System",
            "details": log.details,
            "ip_address": log.ip_address,
            "timestamp": log.timestamp.isoformat() if log.timestamp else None
        })
    
    return {
        "total": total,
        "page": page,
        "limit": limit,
        "logs": result
    }

# ================ EXPORTS ================

@router.get("/export/transactions")
async def export_transactions_csv(
    admin=Depends(verify_admin),
    db: Session = Depends(get_db)
):
    """Export all transactions as CSV"""
    transactions = db.query(Transaction).join(User).order_by(Transaction.timestamp).all()
    
    # Create CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write header
    writer.writerow(['ID', 'User ID', 'Username', 'Amount', 'Type', 'Reference', 'Status', 'Timestamp'])
    
    # Write data
    for tx in transactions:
        writer.writerow([
            tx.id,
            tx.user_id,
            tx.user.username if tx.user else 'N/A',
            tx.amount,
            tx.type,
            tx.reference_id or '',
            tx.status,
            tx.timestamp.isoformat() if tx.timestamp else ''
        ])
    
    # Return as file
    output.seek(0)
    return FileResponse(
        path=output.getvalue(),
        media_type='text/csv',
        filename=f'transactions_export_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.csv'
    )

@router.get("/export/users")
async def export_users_csv(
    admin=Depends(verify_admin),
    db: Session = Depends(get_db)
):
    """Export all users as CSV"""
    users = db.query(User).all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    writer.writerow(['ID', 'Telegram ID', 'Username', 'First Name', 'Last Name', 
                     'Balance', 'Blocked', 'Admin', 'Created', 'Last Active'])
    
    for user in users:
        writer.writerow([
            user.id,
            user.telegram_id,
            user.username or '',
            user.first_name or '',
            user.last_name or '',
            user.wallet_balance,
            user.is_blocked,
            user.is_admin,
            user.created_at.isoformat() if user.created_at else '',
            user.last_active.isoformat() if user.last_active else ''
        ])
    
    output.seek(0)
    return FileResponse(
        path=output.getvalue(),
        media_type='text/csv',
        filename=f'users_export_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.csv'
    )

# ================ SYSTEM CONTROLS ================

@router.post("/system/restart-round-worker")
async def restart_round_worker(
    admin=Depends(verify_admin)
):
    """Restart the round worker"""
    await round_worker.stop()
    await round_worker.start()
    
    return {"success": True, "message": "Round worker restarted"}

@router.get("/system/health")
async def system_health(
    admin=Depends(verify_admin),
    db: Session = Depends(get_db)
):
    """Get system health status"""
    # Check database
    try:
        db.execute("SELECT 1").scalar()
        db_status = "healthy"
    except:
        db_status = "unhealthy"
    
    # Check Redis
    from redis_client import redis_client
    try:
        redis_client.client.ping()
        redis_status = "healthy"
    except:
        redis_status = "unhealthy"
    
    # Get system metrics
    active_rounds = db.query(Round).filter(Round.status == 'active').count()
    total_users = db.query(User).count()
    pending_transactions = db.query(Transaction).filter(Transaction.status == 'pending').count()
    
    return {
        "status": "healthy" if db_status == "healthy" and redis_status == "healthy" else "degraded",
        "database": db_status,
        "redis": redis_status,
        "metrics": {
            "active_rounds": active_rounds,
            "total_users": total_users,
            "pending_transactions": pending_transactions,
            "timestamp": datetime.utcnow().isoformat()
        }
    }