from flask import Flask, request, jsonify
import time
import uuid
import hashlib
import json
import threading


app = Flask(__name__)

# The store: an in-memory dictionary mapping each idempotency key 
# to a record of what we've stored for it.
store = {}

# The lock that protects all reads and write to the store.import
# Acquring this lock guarantees no other thread is reading or 
#writing the store at the same moment.import
store_lock = threading.Lock()

def hash_body(body_dict):
    """ Produce a stable fingerprint of the request body.
    
    Two requests with the same content should produce the same hash,
    even if their JSON was formatted with keys in a different order."""
    canonical = json.dumps(body_dict, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


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

            # Conflict: same key, different body
            if record["body_hash"] != body_hash:
                return jsonify({
                    "error": "Idempotency key already used for a different request body"
                }), 422

            # Duplicate match — but is the response ready?
            if record["status"] == "IN_FLIGHT":
                # Response not ready yet. Grab the event and release the lock.
                # We'll wait OUTSIDE the lock to avoid blocking the owner.
                wait_event = record["done_event"]
            else:
                # Response is ready (status is COMPLETED). Replay it now.
                response = jsonify(record["response"])
                response.headers["X-Cache-Hit"] = "true"
                return response, record["status_code"]
        else:
            # Brand-new key: reserve it
            store[key] = {
                "status": "IN_FLIGHT",
                "body_hash": body_hash,
                "response": None,
                "status_code": None,
                "done_event": threading.Event(),   # ← NEW
            }
            is_owner = True

    # If we found an IN_FLIGHT record, wait for the owner to finish
    if wait_event is not None:
        wait_event.wait(timeout=10)   # safety timeout
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
    store[key]["done_event"].set()   # ← NEW

    # Step 8: return the response
    response = jsonify(response_body)
    response.headers["X-Cache-Hit"] = "false"
    return response, status_code

if __name__ == "__main__":
    app.run(port=5000, debug=True)




  
