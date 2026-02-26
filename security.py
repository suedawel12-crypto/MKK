import hmac
import hashlib
import json
from typing import Dict, Any
from datetime import datetime, timedelta
from fastapi import Request, HTTPException
from urllib.parse import parse_qsl

from config import settings

class SecurityManager:
    @staticmethod
    def verify_telegram_init_data(init_data: str) -> bool:
        """Verify Telegram WebApp initialization data"""
        try:
            parsed_data = dict(parse_qsl(init_data))
            hash_value = parsed_data.pop('hash', '')
            
            # Create data check string
            data_check_string = '\n'.join(
                f"{k}={v}" for k, v in sorted(parsed_data.items())
            )
            
            # Compute secret key
            secret_key = hmac.new(
                b"WebAppData",
                settings.BOT_TOKEN.encode(),
                hashlib.sha256
            ).digest()
            
            # Compute hash
            calculated_hash = hmac.new(
                secret_key,
                data_check_string.encode(),
                hashlib.sha256
            ).hexdigest()
            
            return hmac.compare_digest(calculated_hash, hash_value)
        except:
            return False
    
    @staticmethod
    def generate_jwt(user_id: int) -> str:
        """Generate JWT for admin panel"""
        import jwt
        payload = {
            'user_id': user_id,
            'exp': datetime.utcnow() + timedelta(hours=24)
        }
        return jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')
    
    @staticmethod
    def verify_jwt(token: str) -> Dict:
        """Verify JWT token"""
        import jwt
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])
            return payload
        except jwt.InvalidTokenError:
            raise HTTPException(status_code=401, detail="Invalid token")

class FraudDetector:
    def __init__(self, db, redis_client):
        self.db = db
        self.redis = redis_client
    
    async def check_suspicious_activity(self, user_id: int, ip: str, action: str) -> bool:
        """Check for suspicious patterns"""
        from database import User, AuditLog
        
        # Get user
        user = self.db.query(User).filter(User.telegram_id == str(user_id)).first()
        if not user:
            return False
        
        # Check multiple accounts from same IP
        same_ip_users = self.db.query(User).filter(
            User.ip_addresses.contains([ip])
        ).count()
        
        if same_ip_users > 3:
            await self._flag_user(user.id, "Multiple accounts from same IP")
            return True
        
        # Check rapid wins
        if action == "claim":
            recent_wins = self.db.query(AuditLog).filter(
                AuditLog.user_id == user.id,
                AuditLog.action == "win",
                AuditLog.timestamp > datetime.utcnow() - timedelta(minutes=5)
            ).count()
            
            if recent_wins > 2:
                await self._flag_user(user.id, "Rapid wins detected")
                return True
        
        # Check pattern mismatch (impossible win)
        if action == "claim":
            # Verify if numbers called actually match card
            # This will be handled in the claim function
            pass
        
        return False
    
    async def _flag_user(self, user_id: int, reason: str):
        """Flag user for suspicious activity"""
        from database import AuditLog
        
        audit = AuditLog(
            action="suspicious_activity",
            user_id=user_id,
            details={"reason": reason}
        )
        self.db.add(audit)
        self.db.commit()
        
        # Cache flag
        await self.redis.set_cache(f"flag:{user_id}", reason, 3600)

security_manager = SecurityManager()