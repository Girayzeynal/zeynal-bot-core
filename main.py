import os
from flask import Flask, request, jsonify
from faz13_engine import faz13_orchestrator as orchestrator
from faz22_engine import faz22_meta as meta

app = Flask(__name__)
# Load configuration from meta (production settings)
app.config.from_object(meta.Config)

@app.route("/", methods=["GET"])
def home():
    # A simple route for health check or index
    return "OddsBot is running!", 200

@app.route("/webhook", methods=["POST"])
def webhook():
    """
    Telegram will send updates (messages) to this endpoint as webhooks.
    """
    update = request.get_json()
    # Process the update using orchestrator
    orchestrator.handle_update(update)
    # Return a 200 to acknowledge the update was received successfully
    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    # Running app in debug mode for development (if needed)
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port) 
