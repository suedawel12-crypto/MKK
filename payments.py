from fastapi import APIRouter, Request, HTTPException
from sqlalchemy.orm import Session
import stripe
import hmac
import hashlib
import json

from database import get_db, User, Transaction
from config import settings

router = APIRouter(prefix="/payments", tags=["payments"])

# Stripe configuration
stripe.api_key = settings.STRIPE_SECRET_KEY

@router.post("/create-payment")
async def create_payment(request: Request, db: Session = Depends(get_db)):
    """Create a payment intent"""
    data = await request.json()
    user_id = data.get("user_id")
    amount = data.get("amount")  # in dollars
    
    # Get user
    user = db.query(User).filter(User.telegram_id == str(user_id)).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    try:
        # Create Stripe payment intent
        intent = stripe.PaymentIntent.create(
            amount=int(amount * 100),  # cents
            currency='usd',
            metadata={
                'user_id': user_id,
                'user_telegram_id': user.telegram_id
            }
        )
        
        return {
            'client_secret': intent.client_secret,
            'payment_intent_id': intent.id
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/stripe-webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """Handle Stripe webhook"""
    payload = await request.body()
    sig_header = request.headers.get('stripe-signature')
    
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    
    # Handle the event
    if event['type'] == 'payment_intent.succeeded':
        payment_intent = event['data']['object']
        
        # Credit user
        user_id = payment_intent['metadata']['user_id']
        amount = payment_intent['amount'] / 100  # convert back to dollars
        
        user = db.query(User).filter(User.telegram_id == user_id).first()
        if user:
            user.wallet_balance += amount
            
            transaction = Transaction(
                user_id=user.id,
                amount=amount,
                type='deposit',
                reference_id=payment_intent['id']
            )
            db.add(transaction)
            db.commit()
    
    return {"status": "success"}

# Telegram Stars payment (if using)
@router.post("/telegram-stars")
async def telegram_stars_payment(request: Request, db: Session = Depends(get_db)):
    """Handle Telegram Stars payment"""
    data = await request.json()
    
    # Verify Telegram signature
    # Implementation depends on Telegram Stars API
    
    user_id = data.get('user_id')
    amount = data.get('amount')
    payload = data.get('payload')
    
    # Credit user
    user = db.query(User).filter(User.telegram_id == str(user_id)).first()
    if user:
        user.wallet_balance += amount
        
        transaction = Transaction(
            user_id=user.id,
            amount=amount,
            type='deposit',
            reference_id=payload
        )
        db.add(transaction)
        db.commit()
    
    return {"ok": True}