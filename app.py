# ___ Imports _________________________________________________________

from flask import Flask, request, jsonify
import time
import uuid
import hashlib
import json
import threading
import logging
from datetime import datetime


# ___ App Setup _______________________________________________________
app = Flask(__name__)


# ___ Audit logging __________________________________________________
# Audit events are written to stdout. In production, these would go
# to a dedicated log sink (seperate file, syslog, or a managed service)
# with stricter retention and access-control requirements than
# application logs.

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("idempotency-gateway")


def audit(decision, key, client_ip, extra=""):
    """Emit one structured audit-log line per request decision."""
    logger.info(f"decision={decision} key={key} client_ip={client_ip} {extra}")


# ___ TTL expiry ______________________________________________________
# 24-hour expiry on idempotency keys. Matches Stripe's default. Bounds
# the in-memory store's growth and caps the replay-attack window if a
# key were ever intercepted.

KEY_TTL_SECONDS = 24 * 60 * 60


def is_expired(record):
    """A record is expired if its age exceeds KEY_TTL_SECONDS."""
    age = time.time() - record["created_at"]
    return age > KEY_TTL_SECONDS 


# ___ Store and helpers _______________________________________________
# The store: an in-memory dictionary mapping each idempotency key 
# to a record of what we've stored for it.

store = {}

# The lock that protects all reads and write to the store import
# Acquiring this lock guarantees no other thread is reading or 
# write the store at the same moment.

store_lock = threading.Lock()

def hash_body(body_dict):
    """ Produce a stable fingerprint of the request body.
    
    Two requests with the same content should produce the same hash,
    even if their JSON was formatted with keys in a different order."""
    canonical = json.dumps(body_dict, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


# ___ HTTP endpoint ____________________________________________________

@app.route("/process-payment", methods=["POST"])
def process_payment():
    # Step 1: validate the Idempotency-Key header
    key = request.headers.get("Idempotency-Key")
    if not key:
        return jsonify({"error": "Idempotency-Key header is required"}), 400

    # Step 2: read and validate the body
    body = request.get_json(silent=True)
    if body is None:
        return jsonify({"error": "Request body must be valid JSON"}), 400
    if "amount" not in body or "currency" not in body:
        return jsonify({"error": "Body must contain 'amount' and 'currency' fields"}), 400

    # Step 3: compute a fingerprint of the body
    body_hash = hash_body(body)

    # Step 4 + 5: atomic check-and-claim, plus identify if we need to wait
    is_owner = False
    wait_event = None   # ← NEW: set to the record's event if we need to wait
    with store_lock:
        if key in store:
            record = store[key]

            # TTL expiry check - treat expired records as if they were never there
            if is_expired(record):
                audit("EXPIRED_PURGED", key, request.remote_addr)
                del store[key]
            else:
                # Conflict: same key, different body
                if record["body_hash"] != body_hash:
                    audit("CONfLICT_422", key, request.remote_addr)
                    return jsonify({
                        "error": "Idempotency key already used for a different request body"
                    }), 422

                # Duplicate match — but is the response ready?
                if record["status"] == "IN_FLIGHT":
                    audit("WAIT_FOR_FLIGHT", key, request.remote_addr)
                    # Response not ready yet. Grab the event and release the lock.
                    # We'll wait OUTSIDE the lock to avoid blocking the owner.
                    wait_event = record["done_event"]
                else:
                    # Response is ready (status is COMPLETED). Replay it now.
                    audit("REPLAY_CACHED", key, request.remote_addr)
                    response = jsonify(record["response"])
                    response.headers["X-Cache-Hit"] = "true"
                    return response, record["status_code"]
        # Brand-new key (or expired and just purged): reserve it
        if key not in store:
            store[key] = {
                "status": "IN_FLIGHT",
                "body_hash": body_hash,
                "response": None,
                "status_code": None,
                "done_event": threading.Event(),
                "created_at": time.time(),
            }
            is_owner = True
            audit("NEW_REQUEST", key, request.remote_addr)

    # If we found an IN_FLIGHT record, wait for the owner to finish
    if wait_event is not None:
        wait_event.wait(timeout=10) 
        with store_lock:
            record = store[key]
        response = jsonify(record["response"])
        response.headers["X-Cache-Hit"] = "true"
        return response, record["status_code"]

    # Step 6: we are the owner — process the payment OUTSIDE the lock
    time.sleep(2)
    transaction_id = "txn_" + uuid.uuid4().hex[:12]
    response_body = {
        "status": f"Charged {body['amount']} {body['currency']}",
        "transaction_id": transaction_id,
    }
    status_code = 201

    # Step 7: update the store INSIDE the lock, then signal waiters
    with store_lock:
        store[key]["status"] = "COMPLETED"
        store[key]["response"] = response_body
        store[key]["status_code"] = status_code

    # Signal any threads waiting on this event (must be after the lock release,
    # so waiters can re-acquire the lock to read the now-completed record)

    store[key]["done_event"].set()

    # Step 8: return the response
    response = jsonify(response_body)
    response.headers["X-Cache-Hit"] = "false"
    return response, status_code


# ___ Startup __________________________________________________________
if __name__ == "__main__":
    app.run(port=5000, debug=True)