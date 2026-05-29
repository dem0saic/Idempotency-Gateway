from flask import Flask, request, jsonify
import time
import uuid


app = Flask(__name__)

@app.route("/process-payment", methods=["POST"])
def process_payment():
    # Step 1: recive the request and pull the data out of it
    body = request.get_json()
    
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




  
