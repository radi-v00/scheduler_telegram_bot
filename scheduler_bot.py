import os
import asyncio
from datetime import datetime
import pytz
from flask import Flask, request
import telegram
from telegram.ext import Dispatcher, CommandHandler, MessageHandler, Filters
import asyncpg

TOKEN = os.environ['BOT_TOKEN']
DATABASE_URL = os.environ['NEON_DATABASE_URL']

# Initialize bot
bot = telegram.Bot(token=TOKEN)

# Create dispatcher
dispatcher = Dispatcher(bot, None, workers=0)

# Flask app
app = Flask(__name__)

# Database connection pool (global)
db_pool = None

async def init_db_pool():
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)

@app.before_first_request
def before_first_request():
    loop = asyncio.get_event_loop()
    loop.run_until_complete(init_db_pool())

# ------------------ Command Handlers ------------------
async def start(update, context):
    await update.message.reply_text(
        "Hello! I'm your scheduler bot.\n"
        "Commands:\n"
        "/addtask YYYY-MM-DD HH:MM description\n"
        "/mytasks - list your upcoming tasks\n"
        "/deletetask <task_id>\n"
        "/changetime <task_id> YYYY-MM-DD HH:MM\n"
        "/setroutine <task_id> daily/weekly/monthly\n"
        "/help"
    )

async def addtask(update, context):
    """Add a one-time task. Usage: /addtask 2025-03-20 15:30 Buy milk"""
    try:
        args = context.args
        if len(args) < 3:
            await update.message.reply_text("Usage: /addtask YYYY-MM-DD HH:MM description")
            return
        date_str = args[0]
        time_str = args[1]
        description = ' '.join(args[2:])
        # Combine date and time
        dt_str = f"{date_str} {time_str}"
        scheduled = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
        # Assume user's timezone? For simplicity, store as UTC. Could ask user for timezone.
        scheduled = pytz.UTC.localize(scheduled)  # make it timezone-aware
        user_id = update.effective_user.id

        async with db_pool.acquire() as conn:
            task_id = await conn.fetchval(
                "INSERT INTO tasks (user_id, description, scheduled_time) VALUES ($1, $2, $3) RETURNING id",
                user_id, description, scheduled
            )
        await update.message.reply_text(f"Task added with ID {task_id}")
    except Exception as e:
        await update.message.reply_text(f"Error: {str(e)}")

async def mytasks(update, context):
    """List upcoming tasks"""
    user_id = update.effective_user.id
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, description, scheduled_time FROM tasks WHERE user_id = $1 AND scheduled_time > NOW() ORDER BY scheduled_time LIMIT 20",
            user_id
        )
    if not rows:
        await update.message.reply_text("No upcoming tasks.")
        return
    lines = [f"{row['id']}: {row['description']} at {row['scheduled_time'].strftime('%Y-%m-%d %H:%M UTC')}" for row in rows]
    await update.message.reply_text("Your upcoming tasks:\n" + "\n".join(lines))

async def deletetask(update, context):
    """Delete a task by ID"""
    try:
        task_id = int(context.args[0])
        user_id = update.effective_user.id
        async with db_pool.acquire() as conn:
            result = await conn.execute("DELETE FROM tasks WHERE id = $1 AND user_id = $2", task_id, user_id)
        if result == "DELETE 0":
            await update.message.reply_text("Task not found or not yours.")
        else:
            await update.message.reply_text("Task deleted.")
    except:
        await update.message.reply_text("Usage: /deletetask <task_id>")

async def changetime(update, context):
    """Change scheduled time of a task"""
    try:
        task_id = int(context.args[0])
        date_str = context.args[1]
        time_str = context.args[2]
        dt_str = f"{date_str} {time_str}"
        new_time = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
        new_time = pytz.UTC.localize(new_time)
        user_id = update.effective_user.id
        async with db_pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE tasks SET scheduled_time = $1 WHERE id = $2 AND user_id = $3",
                new_time, task_id, user_id
            )
        if result == "UPDATE 0":
            await update.message.reply_text("Task not found or not yours.")
        else:
            await update.message.reply_text("Task time updated.")
    except:
        await update.message.reply_text("Usage: /changetime <task_id> YYYY-MM-DD HH:MM")

async def setroutine(update, context):
    """Set recurrence for a task"""
    try:
        task_id = int(context.args[0])
        recurrence = context.args[1].lower()
        if recurrence not in ['daily', 'weekly', 'monthly']:
            await update.message.reply_text("Recurrence must be daily, weekly, or monthly.")
            return
        user_id = update.effective_user.id
        async with db_pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE tasks SET recurrence = $1 WHERE id = $2 AND user_id = $3",
                recurrence, task_id, user_id
            )
        if result == "UPDATE 0":
            await update.message.reply_text("Task not found or not yours.")
        else:
            await update.message.reply_text(f"Task recurrence set to {recurrence}.")
    except:
        await update.message.reply_text("Usage: /setroutine <task_id> daily|weekly|monthly")

# Register handlers
dispatcher.add_handler(CommandHandler('start', start))
dispatcher.add_handler(CommandHandler('addtask', addtask))
dispatcher.add_handler(CommandHandler('mytasks', mytasks))
dispatcher.add_handler(CommandHandler('deletetask', deletetask))
dispatcher.add_handler(CommandHandler('changetime', changetime))
dispatcher.add_handler(CommandHandler('setroutine', setroutine))

# Optional: handle unknown commands
async def unknown(update, context):
    await update.message.reply_text("Sorry, I didn't understand that command.")
dispatcher.add_handler(MessageHandler(Filters.command, unknown))

# ------------------ Webhook Endpoint ------------------
@app.route('/webhook', methods=['POST'])
def webhook():
    update = telegram.Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(update)
    return 'ok'

# ------------------ Scheduler Endpoint (for cron) ------------------
@app.route('/check-tasks', methods=['GET'])
def check_tasks():
    """Endpoint that will be called periodically by an external cron service."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(check_due_tasks())
    return 'Checked'