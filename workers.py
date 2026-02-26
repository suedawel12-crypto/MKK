import asyncio
import random
import logging
from datetime import datetime
from sqlalchemy.orm import Session

from database import SessionLocal, Room, Round, CalledNumber, Card, User, Transaction
from redis_client import redis_client
from config import settings

logger = logging.getLogger(__name__)

class RoundWorker:
    def __init__(self):
        self.running = False
        self.active_rounds = {}
    
    async def start(self):
        """Start the round worker"""
        self.running = True
        asyncio.create_task(self._round_loop())
        logger.info("Round worker started")
    
    async def stop(self):
        """Stop the round worker"""
        self.running = False
    
    async def _round_loop(self):
        """Main round processing loop"""
        while self.running:
            try:
                await self._process_rounds()
            except Exception as e:
                logger.error(f"Error in round loop: {e}")
            await asyncio.sleep(1)
    
    async def _process_rounds(self):
        """Process all active rounds"""
        db = SessionLocal()
        
        try:
            # Get active rounds
            active_rounds = db.query(Round).filter(
                Round.status == 'active'
            ).all()
            
            for round in active_rounds:
                await self._process_round(round, db)
            
            # Check for rounds to start
            waiting_rounds = db.query(Round).filter(
                Round.status == 'waiting'
            ).all()
            
            for round in waiting_rounds:
                await self._start_round(round, db)
            
        finally:
            db.close()
    
    async def _process_round(self, round: Round, db: Session):
        """Process an active round"""
        # Check if round should end
        if len(round.numbers_called) >= 75:
            await self._end_round(round, db)
            return
        
        # Call next number if it's time
        last_call = db.query(CalledNumber).filter(
            CalledNumber.round_id == round.id
        ).order_by(CalledNumber.called_at.desc()).first()
        
        if last_call:
            time_since_call = (datetime.utcnow() - last_call.called_at).total_seconds()
            if time_since_call < settings.NUMBER_CALL_INTERVAL:
                return
        
        # Call next number
        await self._call_number(round, db)
    
    async def _call_number(self, round: Round, db: Session):
        """Call a new number"""
        # Get available numbers
        called = set(round.numbers_called)
        available = [n for n in range(1, 76) if n not in called]
        
        if not available:
            return
        
        # Select random number
        number = random.SystemRandom().choice(available)
        
        # Save to database
        called_number = CalledNumber(
            round_id=round.id,
            number=number
        )
        db.add(called_number)
        
        # Update round
        round.numbers_called = list(called) + [number]
        db.commit()
        
        # Broadcast via Redis
        await redis_client.publish(f"room:{round.room_id}", {
            'type': 'number_called',
            'round_id': round.id,
            'number': number,
            'called_numbers': round.numbers_called
        })
        
        logger.info(f"Round {round.id} called number {number}")
    
    async def _start_round(self, round: Round, db: Session):
        """Start a waiting round"""
        round.status = 'active'
        round.start_time = datetime.utcnow()
        db.commit()
        
        await redis_client.publish(f"room:{round.room_id}", {
            'type': 'round_started',
            'round_id': round.id,
            'start_time': round.start_time.isoformat()
        })
        
        logger.info(f"Round {round.id} started")
    
    async def _end_round(self, round: Round, db: Session):
        """End a round (no winner)"""
        round.status = 'completed'
        round.end_time = datetime.utcnow()
        db.commit()
        
        await redis_client.publish(f"room:{round.room_id}", {
            'type': 'round_ended',
            'round_id': round.id
        })
        
        # Create next round
        await self._create_next_round(round.room_id, db)
        
        logger.info(f"Round {round.id} ended - no winner")
    
    async def _create_next_round(self, room_id: int, db: Session):
        """Create the next round for a room"""
        room = db.query(Room).filter(Room.id == room_id).first()
        
        new_round = Round(
            room_id=room_id,
            status='waiting',
            numbers_called=[]
        )
        db.add(new_round)
        db.commit()
        
        await redis_client.publish(f"room:{room_id}", {
            'type': 'new_round',
            'round_id': new_round.id
        })
        
        logger.info(f"Created new round {new_round.id} for room {room_id}")

class ClaimProcessor:
    @staticmethod
    async def process_claim(round_id: int, card_id: int, user_id: int, db: Session) -> dict:
        """Process a claim with Redis lock for atomicity"""
        
        # Acquire lock
        lock_acquired = await redis_client.acquire_lock(f"claim:{round_id}", timeout=5)
        
        if not lock_acquired:
            return {'success': False, 'message': 'Claim is being processed'}
        
        try:
            # Get round and card
            round = db.query(Round).filter(Round.id == round_id).first()
            card = db.query(Card).filter(Card.id == card_id, Card.user_id == user_id).first()
            
            if not round or not card:
                return {'success': False, 'message': 'Invalid round or card'}
            
            if round.status != 'active':
                return {'success': False, 'message': 'Round is not active'}
            
            if card.claimed:
                return {'success': False, 'message': 'Card already claimed'}
            
            # Verify win
            is_winner, numbers_needed = ClaimProcessor._verify_win(
                card.numbers,
                round.numbers_called
            )
            
            if not is_winner:
                return {'success': False, 'message': 'No winning line yet'}
            
            # Check if jackpot (win in ≤40 numbers)
            is_jackpot = len(round.numbers_called) <= 40
            
            # Calculate winnings
            total_pool = round.total_pool
            house_cut = total_pool * settings.HOUSE_COMMISSION
            winner_cut = total_pool * settings.WINNER_COMMISSION
            jackpot_cut = total_pool * settings.JACKPO​COMMISSION
            
            winner_amount = winner_cut + (jackpot_cut if is_jackpot else 0)
            
            # Update round
            round.status = 'jackpot' if is_jackpot else 'completed'
            round.winner_id = user_id
            round.winner_amount = winner_amount
            round.end_time = datetime.utcnow()
            
            # Update card
            card.claimed = True
            
            # Update user wallet
            user = db.query(User).filter(User.id == user_id).first()
            user.wallet_balance += winner_amount
            
            # Create transaction
            transaction = Transaction(
                user_id=user_id,
                amount=winner_amount,
                type='jackpot' if is_jackpot else 'win'
            )
            db.add(transaction)
            
            # Create next round
            new_round = Round(
                room_id=round.room_id,
                status='waiting',
                numbers_called=[]
            )
            db.add(new_round)
            
            db.commit()
            
            # Broadcast win
            await redis_client.publish(f"room:{round.room_id}", {
                'type': 'winner',
                'round_id': round.id,
                'winner_id': user_id,
                'amount': winner_amount,
                'is_jackpot': is_jackpot,
                'numbers_called': len(round.numbers_called)
            })
            
            return {
                'success': True,
                'message': 'Jackpot!' if is_jackpot else 'Winner!',
                'amount': winner_amount,
                'is_jackpot': is_jackpot
            }
            
        finally:
            await redis_client.release_lock(f"claim:{round_id}")
    
    @staticmethod
    def _verify_win(card_numbers: list, called_numbers: list) -> tuple:
        """Verify if card has a winning line"""
        called_set = set(called_numbers)
        
        # Check each row (3 rows in 75-ball)
        for row in card_numbers:
            # Count marked numbers in row
            marked = sum(1 for num in row if num in called_set)
            if marked == 5:  # Full row
                return True, row
        
        return False, []

# Initialize workers
round_worker = RoundWorker()
claim_processor = ClaimProcessor()