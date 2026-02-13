import os
from flask import Flask, request
import telegram
from telegram.ext import Dispatcher, CommandHandler, MessageHandler, Filters

# Initialize bot
TOKEN = os.environ['BOT_TOKEN']
bot = telegram.Bot(token=TOKEN)

# Create dispatcher
dispatcher = Dispatcher(bot, None, workers=0)

# Define handlers (copy from your original bot)
def start(update, context):
    update.message.reply_text('Hello!')

dispatcher.add_handler(CommandHandler('start', start))

# Flask app
app = Flask(__name__)

@app.route('/webhook', methods=['POST'])
def webhook():
    update = telegram.Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(update)
    return 'ok'

# Set webhook on startup (you may need to call this manually once)
# bot.set_webhook(url='https://your-app.vercel.app/webhook')