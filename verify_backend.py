import requests
import json
import time

BASE_URL = "http://localhost:8000/api"

def run_verification():
    # 1. Health Check
    try:
        r = requests.get(f"{BASE_URL}/health")
        print(f"Health: {r.json()}")
    except Exception as e:
        print("Backend not running? Start uvicorn first.")
        return

    # 2. Create Portfolio
    # Mock Auth Header
    headers = {"Authorization": "Bearer test_token"}
    r = requests.post(f"{BASE_URL}/portfolios?name=Enhanced%20Portfolio", headers=headers)
    portfolio = r.json()
    pid = portfolio["id"]
    print(f"Created Portfolio: {pid}")

    # 3. Deposit Cash
    requests.post(f"{BASE_URL}/wallet/transaction?portfolio_id={pid}&type=DEPOSIT&amount=50000", headers=headers)
    print("Deposited $50,000")

    # 4. Strict FIFO - Multiple Buys
    # Buy 1 BTC @ 10,000
    requests.post(f"{BASE_URL}/trades?portfolio_id={pid}&coin_id=bitcoin&symbol=BTC&type=BUY&price=10000&quantity=1&fee=10", headers=headers)
    print("Bought 1 BTC @ $10,000 (Fee $10)")
    
    # Buy 1 BTC @ 20,000
    requests.post(f"{BASE_URL}/trades?portfolio_id={pid}&coin_id=bitcoin&symbol=BTC&type=BUY&price=20000&quantity=1&fee=20", headers=headers)
    print("Bought 1 BTC @ $20,000 (Fee $20)")
    
    # 5. Sell 1.5 BTC @ 30,000
    # FIFO Expectation (buy fees included in cost basis):
    # Lot 1 cost basis = (10000 + 10 fee) / 1 = 10010/unit
    # Lot 2 cost basis = (20000 + 20 fee) / 1 = 20020/unit
    # 1. Consume 1 BTC from Lot 1. PnL = (30000 - 10010) * 1 = 19990.
    # 2. Consume 0.5 BTC from Lot 2. PnL = (30000 - 20020) * 0.5 = 4990.
    # Total Gross PnL = 24980.
    # Subtract Sell Fee = 30.
    # Net Realized PnL = 24980 - 30 = 24950.
    
    print("Selling 1.5 BTC @ $30,000 (Fee $30)...")
    r = requests.post(f"{BASE_URL}/trades?portfolio_id={pid}&coin_id=bitcoin&symbol=BTC&type=SELL&price=30000&quantity=1.5&fee=30", headers=headers)
    result = r.json()
    print(f"Sell Result: {result}")
    
    # Verify PnL
    expected_pnl = 24950.0
    actual_pnl = result.get('realized_pnl')
    
    if abs(actual_pnl - expected_pnl) < 1.0:
        print(f"✅ FIFO Logic Verified! Realized PnL: {actual_pnl}")
    else:
        print(f"❌ Verification Failed. Expected {expected_pnl}, got {actual_pnl}")

    # 6. Verify Remaining Position
    # Should have 0.5 BTC remaining from the 20k lot.
    # Cost Basis = 10k (0.5 * 20k) + Fee portion? 
    # Actually our Calculator aggregates remaining lots.
    
    r = requests.get(f"{BASE_URL}/portfolio/{pid}/positions", headers=headers)
    positions = r.json()
    btc_pos = next((p for p in positions if p['symbol'] == 'BTC'), None)
    
    if btc_pos:
        print(f"Remaining Position: {btc_pos['units']} units @ Avg {btc_pos['avg_price']}")
        if btc_pos['units'] == 0.5:
             print("✅ Remaining Units Verified!")
        else:
             print(f"❌ Remaining Units Wrong. Expected 0.5, got {btc_pos['units']}")


if __name__ == "__main__":
    run_verification()
