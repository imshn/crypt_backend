from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from pathlib import Path
import os

load_dotenv(dotenv_path=Path(__file__).parent / ".env.local")
from sqlmodel import Session, select
from typing import List, Optional
from datetime import datetime
from database import create_db_and_tables, get_session
from models import User, Portfolio, Trade, TaxLot, WalletTransaction, TradeType
from services.lot_manager import LotManager
from services.calculator import Calculator
from coingecko_client import CoinGeckoClient
from auth import get_current_user

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3000",
        "http://192.168.1.2:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def on_startup():
    create_db_and_tables()

@app.get("/api/health")
def health_check():
    return {"status": "ok"}

# --- Portfolios ---
@app.post("/api/portfolios", response_model=Portfolio)
def create_portfolio(name: str, user_id: str = Depends(get_current_user), session: Session = Depends(get_session)):
    user = session.exec(select(User).where(User.clerk_id == user_id)).first()
    if not user:
        user = User(clerk_id=user_id, email="test@example.com")
        session.add(user)
        session.commit()
    
    portfolio = Portfolio(name=name, user_id=user.id)
    session.add(portfolio)
    session.commit()
    session.refresh(portfolio)
    return portfolio

@app.get("/api/portfolios", response_model=List[Portfolio])
def get_portfolios(user_id: str = Depends(get_current_user), session: Session = Depends(get_session)):
    user = session.exec(select(User).where(User.clerk_id == user_id)).first()
    if not user:
        return []
    return user.portfolios

# --- Coin Search ---
@app.get("/api/coins/search")
def search_coins(q: str):
    """Search for coins by name/symbol, returns results with live prices."""
    if len(q.strip()) < 1:
        return []
    client = CoinGeckoClient()
    return client.search_coins(q.strip())

@app.get("/api/coins/{coin_id}/ohlc")
def get_coin_ohlc(coin_id: str, days: int = 7):
    """Get OHLC candlestick data for a coin."""
    if days not in [1, 7, 14, 30, 90, 180, 365]:
        days = 7
    client = CoinGeckoClient()
    return client.get_ohlc(coin_id, days)

# --- Wallet ---
@app.post("/api/wallet/transaction")
def wallet_transaction(portfolio_id: int, type: str, amount: float, session: Session = Depends(get_session)):
    txn = WalletTransaction(portfolio_id=portfolio_id, type=type, amount=amount)
    session.add(txn)
    session.commit()
    return {"status": "success", "txn_id": txn.id}

# --- Trades ---
@app.post("/api/trades")
def add_trade(portfolio_id: int, coin_id: str, symbol: str, type: str, price: float, quantity: float, fee: float = 0.0, fee_type: str = "FIXED", target_lot_id: Optional[int] = Query(None), session: Session = Depends(get_session)):
    # Calculate absolute fee if percentage
    actual_fee = fee
    if fee_type.upper() == "PERCENTAGE":
        actual_fee = (price * quantity) * (fee / 100.0)

    # 1. Record Trade
    trade = Trade(
        portfolio_id=portfolio_id,
        target_lot_id=target_lot_id,
        coin_id=coin_id,
        symbol=symbol,
        type=type, # BUY/SELL
        price=price,
        quantity=quantity,
        fee=actual_fee,
        fee_type=fee_type.upper()
    )
    session.add(trade)
    session.commit()
    session.refresh(trade)
    
    # 2. Lot Logic (FIFO)
    lot_manager = LotManager(session)
    realized_pnl = 0.0
    
    try:
        if type.upper() == "BUY":
            lot_manager.process_buy(trade)
        elif type.upper() == "SELL":
            realized_pnl = lot_manager.process_sell(trade)
    except ValueError as e:
        session.delete(trade) # Rollback trade if lot logic fails
        session.commit()
        raise HTTPException(status_code=400, detail=str(e))
            
    # 3. Update Cash Balance
    # Fee is always deducted from cash? 
    # Or is fee part of cost basis? 
    # For simplicity: Cash Impact = -(Total Value + Fee) if BUY.
    # Cash Impact = (Total Value - Fee) if SELL.
    
    total_val = price * quantity
    cash_change = 0.0
    
    if type.upper() == "BUY":
        cash_change = -(total_val + actual_fee)
    else:
        cash_change = (total_val - actual_fee)
        
    txn_type = "DEPOSIT" if cash_change > 0 else "WITHDRAW"
    
    wallet_txn = WalletTransaction(
        portfolio_id=portfolio_id,
        type=txn_type,
        amount=abs(cash_change),
        timestamp=datetime.utcnow()
    )
    session.add(wallet_txn)
    session.commit()

    return {"trade_id": trade.id, "realized_pnl": realized_pnl}

@app.get("/api/trades", response_model=List[Trade])
def get_trades(portfolio_id: int, session: Session = Depends(get_session)):
    trades = session.exec(select(Trade).where(Trade.portfolio_id == portfolio_id).order_by(Trade.timestamp.desc())).all()
    return trades

@app.get("/api/portfolio/{portfolio_id}/positions/{coin_id}")
def get_position_detail(portfolio_id: int, coin_id: str, session: Session = Depends(get_session)):
    """Fetch metrics for a specific coin in a portfolio, even if balance is zero."""
    calc = Calculator(session)
    return calc.get_position_detail(portfolio_id, coin_id)

@app.get("/api/portfolio/{portfolio_id}/positions/{coin_id}/lots")
def get_position_lots(portfolio_id: int, coin_id: str, session: Session = Depends(get_session)):
    """Fetch all open tax lots for a specific coin in a portfolio."""
    statement = (
        select(TaxLot)
        .join(Trade)
        .where(Trade.portfolio_id == portfolio_id)
        .where(Trade.coin_id == coin_id)
        .where(TaxLot.remaining_qty > 0)
        .order_by(TaxLot.timestamp.asc())
    )
    lots = session.exec(statement).all()
    
    # Return lots with some trade context
    return [
        {
            "id": lot.id,
            "trade_id": lot.trade_id,
            "symbol": lot.trade.symbol,
            "purchase_price": lot.trade.price,
            "original_qty": lot.original_qty,
            "remaining_qty": lot.remaining_qty,
            "cost_basis": lot.cost_basis,
            "fee": lot.trade.fee,
            "timestamp": lot.timestamp
        }
        for lot in lots
    ]

# --- Dashboard & Positions (Calculated View) ---
@app.get("/api/portfolio/{portfolio_id}/positions")
def get_positions(portfolio_id: int, session: Session = Depends(get_session)):
    calc = Calculator(session)
    return calc.get_positions(portfolio_id)

@app.get("/api/portfolio/{portfolio_id}/summary")
def get_summary(portfolio_id: int, session: Session = Depends(get_session)):
    calc = Calculator(session)
    
    # Get Cash Balance
    txns = session.exec(select(WalletTransaction).where(WalletTransaction.portfolio_id == portfolio_id)).all()
    cash_balance = sum([t.amount if t.type == "DEPOSIT" else -t.amount for t in txns])
    
    metrics = calc.get_summary(portfolio_id)
    
    return {
        "cash_balance": cash_balance,
        "crypto_balance": metrics["total_value"],
        "total_net_worth": cash_balance + metrics["total_value"],
        "metrics": metrics
    }


# when executed directly allow customizing host/port via env vars (Render uses PORT)
if __name__ == "__main__":
    import uvicorn
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 8000))
    reload = os.getenv("ENV", "dev") != "prod"
    uvicorn.run("main:app", host=host, port=port, reload=reload)
