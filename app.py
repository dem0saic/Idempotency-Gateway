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
    


    # Step 2: simulate the payment processing (2-second pause)
    time.sleep(2)

    # Step 3: generate a unique transaction Identifier
    transaction_id = "txn_" + uuid.uuid4().hex[:12]

    # step 4: return a response
    response = {
        "status": f"Charged {body['amount']} {body['currency']}",
        "transaction_id": transaction_id
    }
    return jsonify(response), 201


if __name__ == "__main__":
    app.run(port=5000, debug=True)




  
