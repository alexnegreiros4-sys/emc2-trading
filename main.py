from flask import Flask, request, jsonify
import hmac
import hashlib
import time
import requests
import os
import logging

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BINANCE_API_KEY = os.environ.get("BINANCE_API_KEY", "")
BINANCE_PRIVATE_KEY_PATH = os.environ.get("BINANCE_PRIVATE_KEY_PATH", "emc2_binance")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "emc2_secret_2026")
SYMBOL = os.environ.get("SYMBOL", "ETHUSDT")
LEVERAGE = int(os.environ.get("LEVERAGE", "25"))
QUANTITY = float(os.environ.get("QUANTITY", "0.01"))
BASE_URL = "https://fapi.binance.com"

def get_private_key():
    try:
        with open(BINANCE_PRIVATE_KEY_PATH, "r") as f:
            return f.read()
    except:
        return os.environ.get("BINANCE_PRIVATE_KEY", "")

def sign_request(params: dict) -> str:
    from cryptography.hazmat.primitives import serialization, hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.backends import default_backend
    import base64
    
    query_string = "&".join([f"{k}={v}" for k, v in params.items()])
    private_key_pem = get_private_key()
    private_key = serialization.load_pem_private_key(
        private_key_pem.encode(),
        password=None,
        backend=default_backend()
    )
    signature = private_key.sign(query_string.encode(), padding.PKCS1v15(), hashes.SHA256())
    return base64.b64encode(signature).decode()

def set_leverage():
    try:
        params = {
            "symbol": SYMBOL,
            "leverage": LEVERAGE,
            "timestamp": int(time.time() * 1000)
        }
        params["signature"] = sign_request(params)
        headers = {"X-MBX-APIKEY": BINANCE_API_KEY}
        r = requests.post(f"{BASE_URL}/fapi/v1/leverage", params=params, headers=headers)
        logger.info(f"Leverage set: {r.json()}")
    except Exception as e:
        logger.error(f"Leverage error: {e}")

def close_position():
    try:
        params = {"timestamp": int(time.time() * 1000)}
        params["signature"] = sign_request(params)
        headers = {"X-MBX-APIKEY": BINANCE_API_KEY}
        r = requests.get(f"{BASE_URL}/fapi/v2/positionRisk", params=params, headers=headers)
        positions = r.json()
        
        for pos in positions:
            if pos["symbol"] == SYMBOL:
                amt = float(pos["positionAmt"])
                if amt != 0:
                    side = "SELL" if amt > 0 else "BUY"
                    close_params = {
                        "symbol": SYMBOL,
                        "side": side,
                        "type": "MARKET",
                        "quantity": abs(amt),
                        "reduceOnly": "true",
                        "timestamp": int(time.time() * 1000)
                    }
                    close_params["signature"] = sign_request(close_params)
                    r2 = requests.post(f"{BASE_URL}/fapi/v1/order", params=close_params, headers=headers)
                    logger.info(f"Position closed: {r2.json()}")
    except Exception as e:
        logger.error(f"Close position error: {e}")

def open_position(side: str):
    try:
        params = {
            "symbol": SYMBOL,
            "side": side,
            "type": "MARKET",
            "quantity": QUANTITY,
            "timestamp": int(time.time() * 1000)
        }
        params["signature"] = sign_request(params)
        headers = {"X-MBX-APIKEY": BINANCE_API_KEY}
        r = requests.post(f"{BASE_URL}/fapi/v1/order", params=params, headers=headers)
        logger.info(f"Position opened {side}: {r.json()}")
        return r.json()
    except Exception as e:
        logger.error(f"Open position error: {e}")
        return {"error": str(e)}

@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "EMC2 Trading System Online", "symbol": SYMBOL})

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        secret = request.args.get("secret", "")
        if secret != WEBHOOK_SECRET:
            logger.warning("Unauthorized webhook attempt")
            return jsonify({"error": "Unauthorized"}), 401

        data = request.get_json(force=True)
        message = data.get("message", "").strip().lower()
        logger.info(f"Signal received: {message}")

        set_leverage()

        if "ut long" in message or "buy" in message:
            logger.info(">>> EMC2: LONG signal — closing short, opening long")
            close_position()
            time.sleep(0.5)
            result = open_position("BUY")
            return jsonify({"action": "LONG", "result": result})

        elif "ut short" in message or "sell" in message:
            logger.info(">>> EMC2: SHORT signal — closing long, opening short")
            close_position()
            time.sleep(0.5)
            result = open_position("SELL")
            return jsonify({"action": "SHORT", "result": result})

        else:
            logger.warning(f"Unknown signal: {message}")
            return jsonify({"warning": f"Unknown signal: {message}"}), 400

    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
