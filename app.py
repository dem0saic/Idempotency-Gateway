# pyrefly: ignore [missing-import]
from flask import Flask, request, jsonify
import time
import uuid
import hashlib
import json


app = Flask(__name__)
# The store: an in-memory dictionary mapping each idempotency key 
# to a record of what we've stored for it.
store = {}


def hash_body(body_dict):
    """ Produce a stable fingerprint of the request body.
    
    Two requests with the same content should produce the same hash,
    even if their JSON was formatted with keys in a different order."""
    canonical = json.dumps(body_dict, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


@app.route("/process-payment", methods=["POST"])
def process_payment():
    # Step 1: Validate the Idempotency-Key header
    key = request.headers.get("Idempotency-Key")
    if not key:
        return jsonify({"error": "Idempotency-Key header is required"}), 400

    # Step 2: read and validate the body    
    body = request.get_json(silent=True)
    if body is None:
        return jsonify({"error": "Request body must be valid JSON"}), 400
    if "amount" not in body or "currency" not in body:
        return jsonify({"error": "Body must contain 'amount' and 'currency' fields"}), 400
    
    # Step 3: Compute a fingerprint of body
    body_hash = hash_body(body)

    # Step 4: look up the key in the store
    if key in store:
        record = store[key]

        # Step 5: compare body hashes
        if record["body_hash"] != body_hash:
            # Outcome 3: key reused with a different body - conflict
            return jsonify({
                "error": "Idempotency key already used for a different request body"
            }), 422

        # Outcome 5: legitimate duplicate - replay the cached response
        response = jsonify(record["response"])
        response.headers["X-Cache-Hit"] = "true"
        return response, record["status_code"]

    # Outcome 4 path begins here: brand-new key, reserve it in the store
    store[key] = {
        "status": "IN_FLIGHT",
        "body_hash": body_hash,
        "response": None,
        "status_code": None
    }

    # Step 2: simulate the payment processing (2-second pause)
    time.sleep(2)

    # Step 3: generate a unique transaction Identifier
    transaction_id = "txn_" + uuid.uuid4().hex[:12]

    # Build the response
    response_body = {
        "status": f"Charged {body['amount']} {body['currency']}",
        "transaction_id": transaction_id
    }
    status_code = 201

    # Update the store: mark the key as COMPLETED and cache the response
    store[key]["status"] = "COMPLETED"
    store[key]["response"] = response_body
    store[key]["status_code"] = status_code

    # Return the response with X-Cache-Hit: false (this was a fresh execution)
    response = jsonify(response_body)
    response.headers["X-Cache-Hit"] = "false"
    return response, status_code


if __name__ == "__main__":
    app.run(port=5000, debug=True)




  
