import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from sqlalchemy.orm import Session
import json

from config import settings
from database import get_db, User, Room, Round, Transaction
from redis_client import redis_client
from security import security_manager

logger = logging.getLogger(__name__)

class BingoBot:
    def __init__(self):
        self.token = settings.BOT_TOKEN
        self.app = Application.builder().token(self.token).build()
        self._register_handlers()
        print("✅ Bot initialized")
    
    def _register_handlers(self):
        self.app.add_handler(CommandHandler("start", self.start_command))
        self.app.add_handler(CommandHandler("play", self.play_command))
        self.app.add_handler(CommandHandler("wallet", self.wallet_command))
        self.app.add_handler(CommandHandler("admin", self.admin_command))
        self.app.add_handler(CallbackQueryHandler(self.button_handler))
        print("✅ Bot handlers registered")
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        user = update.effective_user
        logger.info(f"User {user.id} started the bot")
        
        # Register user in database
        db = next(get_db())
        try:
            db_user = db.query(User).filter(User.telegram_id == str(user.id)).first()
            
            if not db_user:
                db_user = User(
                    telegram_id=str(user.id),
                    username=user.username,
                    first_name=user.first_name,
                    last_name=user.last_name,
                    wallet_balance=0.0
                )
                db.add(db_user)
                db.commit()
                logger.info(f"New user registered: {user.id}")
            else:
                logger.info(f"Existing user: {user.id}")
            
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
            
        except Exception as e:
            logger.error(f"Error in start_command: {e}")
            await update.message.reply_text("Sorry, an error occurred. Please try again later.")
        finally:
            db.close()
    
    async def play_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /play command"""
        keyboard = [[
            InlineKeyboardButton("🎮 Open Bingo", web_app=WebAppInfo(url=f"{settings.WEBHOOK_URL}/webapp"))
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Click to open Bingo!", reply_markup=reply_markup)
    
    async def wallet_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /wallet command"""
        db = next(get_db())
        try:
            user = db.query(User).filter(User.telegram_id == str(update.effective_user.id)).first()
            
            if user:
                text = f"💰 Your wallet balance: **${user.wallet_balance:.2f}**"
            else:
                text = "Please /start first"
            
            await update.message.reply_text(text)
        finally:
            db.close()
    
    async def admin_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /admin command"""
        user_id = update.effective_user.id
        
        # Check if user is admin
        if user_id not in settings.ADMIN_IDS:
            await update.message.reply_text("⛔ Access denied")
            return
        
        # Create admin panel button
        keyboard = [[
            InlineKeyboardButton(
                "🔧 Open Admin Panel", 
                web_app=WebAppInfo(url=f"{settings.WEBHOOK_URL}/admin")
            )
        ]]
        
        await update.message.reply_text(
            "Welcome to Admin Panel!",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle button callbacks - FIXED VERSION"""
        query = update.callback_query
        await query.answer()
        
        try:
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
                try:
                    user = db.query(User).filter(User.telegram_id == str(update.effective_user.id)).first()
                    
                    if user:
                        # Get user stats
                        total_wins = db.query(Round).filter(Round.winner_id == user.id).count()
                        total_spent = db.query(Transaction).filter(
                            Transaction.user_id == user.id,
                            Transaction.type == "buy_card"
                        ).count()
                        total_won = db.query(Transaction).filter(
                            Transaction.user_id == user.id,
                            Transaction.type.in_(["win", "jackpot"])
                        ).count()
                        
                        stats_text = (
                            f"📊 Your Stats:\n\n"
                            f"🎯 Total Wins: {total_wins}\n"
                            f"💸 Cards Bought: {total_spent}\n"
                            f"🏆 Times Won: {total_won}\n"
                            f"💰 Balance: ${user.wallet_balance:.2f}"
                        )
                    else:
                        stats_text = "No stats available. Please /start first."
                    
                    await query.edit_message_text(
                        stats_text,
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("« Back", callback_data="back")
                        ]])
                    )
                finally:
                    db.close()
            
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
                # Go back to main menu
                db = next(get_db())
                try:
                    user = db.query(User).filter(User.telegram_id == str(update.effective_user.id)).first()
                    balance = user.wallet_balance if user else 0.0
                    
                    welcome_text = (
                        f"🎉 Welcome back to 75-Ball Bingo! 🎉\n\n"
                        f"💰 Your wallet: ${balance:.2f}\n\n"
                        f"🎮 Click Play to start!"
                    )
                    
                    keyboard = [
                        [InlineKeyboardButton("🎮 Play Bingo", web_app=WebAppInfo(url=f"{settings.WEBHOOK_URL}/webapp"))],
                        [InlineKeyboardButton("💰 Deposit", callback_data="deposit"),
                         InlineKeyboardButton("📊 Stats", callback_data="stats")],
                        [InlineKeyboardButton("❓ How to Play", callback_data="help")]
                    ]
                    
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    await query.edit_message_text(welcome_text, reply_markup=reply_markup)
                finally:
                    db.close()
        
        except Exception as e:
            logger.error(f"Error in button_handler: {e}")
            await query.edit_message_text("An error occurred. Please try again.")
    
    async def set_webhook(self):
        """Set webhook for bot"""
        webhook_url = f"{settings.WEBHOOK_URL}/webhook"
        await self.app.bot.set_webhook(url=webhook_url)
        logger.info(f"✅ Webhook set to {webhook_url}")
        print(f"✅ Webhook set to {webhook_url}")

# Initialize bot
bingo_bot = BingoBot()