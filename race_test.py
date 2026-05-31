"""
race_test.py — concurrency test for the idempotency gateway.

Sends multiple simultaneous requests with the same Idempotency-Key
and verifies that all responses contain the same transaction_id
(proof that the payment was processed exactly once).
"""
import threading
import time
import requests

URL = "http://127.0.0.1:5000/process-payment"
KEY = "race-test-005"
BODY = {"amount": 100, "currency": "GHS"}
NUM_REQUESTS = 25

# Shared list to collect results from each thread
results = []
results_lock = threading.Lock()


def send_request(request_id):
    """Send one request and collect its response."""
    start = time.time()
    response = requests.post(
        URL,
        json=BODY,
        headers={"Idempotency-Key": KEY},
    )
    duration = time.time() - start

    with results_lock:
        results.append({
            "request_id": request_id,
            "status_code": response.status_code,
            "x_cache_hit": response.headers.get("X-Cache-Hit"),
            "transaction_id": response.json().get("transaction_id"),
            "duration_seconds": round(duration, 2),
        })


# Start all threads simultaneously
print(f"Firing {NUM_REQUESTS} simultaneous requests with key '{KEY}'...")
threads = [
    threading.Thread(target=send_request, args=(i,))
    for i in range(NUM_REQUESTS)
]

for t in threads:
    t.start()

for t in threads:
    t.join()

# Display results
print("\nResults:")
for result in sorted(results, key=lambda r: r["request_id"]):
    print(
        f"  Request {result['request_id']}: "
        f"status={result['status_code']}, "
        f"X-Cache-Hit={result['x_cache_hit']}, "
        f"txn={result['transaction_id']}, "
        f"duration={result['duration_seconds']}s"
    )

# Verify all responses point to the same transaction
transaction_ids = {r["transaction_id"] for r in results}
print(f"\nUnique transaction IDs: {len(transaction_ids)}")
if len(transaction_ids) == 1:
    print("PASS: All requests returned the same transaction_id.")
    print("      The payment was processed exactly once.")
else:
    print("FAIL: Different transaction IDs detected!")
    print(f"      transaction_ids = {transaction_ids}")
    print("      The system processed the payment multiple times.")