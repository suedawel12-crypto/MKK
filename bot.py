import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from sqlalchemy.orm import Session
import json

from config import settings
from database import get_db, User, Room, Round
from redis_client import redis_client
from security import security_manager

logger = logging.getLogger(__name__)

class BingoBot:
    def __init__(self):
        self.token = settings.BOT_TOKEN
        self.app = Application.builder().token(self.token).build()
        self._register_handlers()
    
    def _register_handlers(self):
        self.app.add_handler(CommandHandler("start", self.start_command))
        self.app.add_handler(CommandHandler("play", self.play_command))
        self.app.add_handler(CommandHandler("wallet", self.wallet_command))
        self.app.add_handler(CallbackQueryHandler(self.button_handler))
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        
        # Register user in database
        db = next(get_db())
        db_user = db.query(User).filter(User.telegram_id == str(user.id)).first()
        
        if not db_user:
            db_user = User(
                telegram_id=str(user.id),
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name
            )
            db.add(db_user)
            db.commit()
        
        # Create welcome message
        welcome_text = (
            f"🎉 Welcome to 75-Ball Bingo! 🎉\n\n"
            f"💰 Your wallet: ${db_user.wallet_balance:.2f}\n\n"
            f"🎮 Click Play to start!"
        )
        
        keyboard = [
            [InlineKeyboardButton("🎮 Play Bingo", web_app=WebAppInfo(url=f"{settings.WEBHOOK_URL}/webapp"))],
            [InlineKeyboardButton("💰 Deposit", callback_data="deposit"),
             InlineKeyboardButton("📊 Stats", callback_data="stats")],
            [InlineKeyboardButton("❓ How to Play", callback_data="help")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(welcome_text, reply_markup=reply_markup)
    
    async def play_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Open WebApp directly"""
        keyboard = [[
            InlineKeyboardButton("🎮 Open Bingo", web_app=WebAppInfo(url=f"{settings.WEBHOOK_URL}/webapp"))
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Click to open Bingo!", reply_markup=reply_markup)
    
    async def wallet_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show wallet balance"""
        db = next(get_db())
        user = db.query(User).filter(User.telegram_id == str(update.effective_user.id)).first()
        
        if user:
            text = f"💰 Your wallet balance: **${user.wallet_balance:.2f}**"
        else:
            text = "Please /start first"
        
        await update.message.reply_text(text)
    
    async def button_handler(self, update: Update, context: ContextTypes.DispatchType):
        query = update.callback_query
        await query.answer()
        
        if query.data == "deposit":
            # Handle deposit
            keyboard = [
                [InlineKeyboardButton("💳 $10", callback_data="deposit_10"),
                 InlineKeyboardButton("💳 $25", callback_data="deposit_25")],
                [InlineKeyboardButton("💳 $50", callback_data="deposit_50"),
                 InlineKeyboardButton("💳 $100", callback_data="deposit_100")],
                [InlineKeyboardButton("« Back", callback_data="back")]
            ]
            await query.edit_message_text(
                "Select amount to deposit:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        
        elif query.data.startswith("deposit_"):
            amount = float(query.data.split("_")[1])
            # Create payment link
            payment_link = f"{settings.WEBHOOK_URL}/pay?amount={amount}&user={update.effective_user.id}"
            await query.edit_message_text(
                f"💳 Click to pay ${amount}:\n{payment_link}\n\nAfter payment, your wallet will be credited automatically.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("« Back", callback_data="deposit")
                ]])
            )
        
        elif query.data == "stats":
            db = next(get_db())
            user = db.query(User).filter(User.telegram_id == str(update.effective_user.id)).first()
            
            # Get user stats
            total_wins = db.query(Round).filter(Round.winner_id == user.id).count()
            total_spent = sum(t.amount for t in user.transactions if t.type == "buy_card")
            total_won = sum(t.amount for t in user.transactions if t.type == "win")
            
            stats_text = (
                f"📊 Your Stats:\n\n"
                f"🎯 Total Wins: {total_wins}\n"
                f"💸 Total Spent: ${total_spent:.2f}\n"
                f"🏆 Total Won: ${total_won:.2f}\n"
                f"📈 Net: ${total_won - total_spent:.2f}"
            )
            
            await query.edit_message_text(
                stats_text,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("« Back", callback_data="back")
                ]])
            )
        
        elif query.data == "help":
            help_text = (
                "❓ How to Play 75-Ball Bingo:\n\n"
                "1️⃣ Buy a card for each round\n"
                "2️⃣ Numbers are called every 5 seconds\n"
                "3️⃣ Mark numbers on your card\n"
                "4️⃣ Click 'Claim' when you have a line\n"
                "5️⃣ Win the pool!\n\n"
                "💰 Jackpot: Win in ≤40 numbers\n"
                "📊 Commission: 20% house, 70% winner, 10% jackpot"
            )
            await query.edit_message_text(
                help_text,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("« Back", callback_data="back")
                ]])
            )
        
        elif query.data == "back":
            await self.start_command(update, context)
    
    async def set_webhook(self):
        """Set webhook for bot"""
        webhook_url = f"{settings.WEBHOOK_URL}/webhook"
        await self.app.bot.set_webhook(url=webhook_url)
        logger.info(f"Webhook set to {webhook_url}")
    
    def run(self):
        """Run bot in polling mode (for development)"""
        self.app.run_polling()

# Initialize bot
bingo_bot = BingoBot()