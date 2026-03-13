from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from pathlib import Path
import os
import time
import requests

load_dotenv(dotenv_path=Path(__file__).parent / ".env.local")
from sqlmodel import Session, select
from typing import List, Optional, Dict, Any
from datetime import datetime
from database import create_db_and_tables, get_session
from models import User, Portfolio, Trade, TaxLot, WalletTransaction, TradeType
from services.lot_manager import LotManager
from services.calculator import Calculator
from coingecko_client import CoinGeckoClient
from auth import get_current_user

app = FastAPI()

SUPPORTED_CURRENCIES = ["USD", "INR", "KWD", "EUR"]
FALLBACK_FX_RATES = {
    "USD": 1.0,
    "INR": 83.0,
    "KWD": 0.307,
    "EUR": 0.92,
}
FX_CACHE_TTL_SECONDS = 60
_fx_cache: Dict[str, Any] = {
    "timestamp": 0.0,
    "payload": None,
}

# CORS configuration.  During development a few localhost
# origins are useful; in production we also need to allow the deployed
# frontend.  To make this future-proof we read a comma-separated list from
# the ALLOWED_ORIGINS env var.
origins = [
    "http://localhost:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3000",
    "http://192.168.1.2:3000",
    "https://multicryptoportfolio.vercel.app",
]
extra = os.getenv("ALLOWED_ORIGINS")
if extra:
    origins.extend([o.strip() for o in extra.split(",") if o.strip()])

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
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


def get_cash_balance(session: Session, portfolio_id: int) -> float:
    txns = session.exec(
        select(WalletTransaction).where(WalletTransaction.portfolio_id == portfolio_id)
    ).all()

    cash_balance = 0.0
    for txn in txns:
        txn_type = (txn.type or "").strip().upper()
        txn_amount = abs(txn.amount or 0.0)
        if txn_type == "DEPOSIT":
            cash_balance += txn_amount
        elif txn_type == "WITHDRAW":
            cash_balance -= txn_amount

    return cash_balance


def get_portfolio_or_404(session: Session, portfolio_id: int) -> Portfolio:
    portfolio = session.exec(
        select(Portfolio).where(Portfolio.id == portfolio_id)
    ).first()
    if not portfolio:
        raise HTTPException(status_code=404, detail=f"Portfolio {portfolio_id} not found")
    return portfolio


def normalize_fee_type(value: Any) -> str:
    raw = value.value if hasattr(value, "value") else str(value or "")
    return raw.strip().upper()


def get_fee_units(quantity: float, fee: float, fee_type: str) -> float:
    if normalize_fee_type(fee_type) != "PERCENTAGE":
        return 0.0
    return quantity * (fee / 100.0)


def get_fee_value(price: float, quantity: float, fee: float, fee_type: str) -> float:
    if normalize_fee_type(fee_type) == "PERCENTAGE":
        return get_fee_units(quantity, fee, fee_type) * price
    return fee


def get_buy_cash_required(total_val: float, fee_value: float, fee_type: str) -> float:
    if normalize_fee_type(fee_type) == "PERCENTAGE":
        return total_val
    return total_val + fee_value


def get_buy_net_quantity(quantity: float, fee: float, fee_type: str) -> float:
    if normalize_fee_type(fee_type) == "PERCENTAGE":
        return quantity - get_fee_units(quantity, fee, fee_type)
    return quantity

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


@app.get("/api/fx/rates")
def get_fx_rates():
    """Return USD-based FX rates for supported display currencies."""
    now = time.time()
    cached_payload = _fx_cache.get("payload")
    cached_ts = float(_fx_cache.get("timestamp") or 0.0)

    if cached_payload and (now - cached_ts) < FX_CACHE_TTL_SECONDS:
        return cached_payload

    symbols = ",".join(c for c in SUPPORTED_CURRENCIES if c != "USD")
    try:
        resp = requests.get(
            "https://api.frankfurter.app/latest",
            params={"from": "USD", "to": symbols},
            timeout=5,
        )
        resp.raise_for_status()
        body = resp.json()
        rates = body.get("rates", {})

        payload = {
            "base": "USD",
            "rates": {
                "USD": 1.0,
                "INR": float(rates.get("INR", 0)),
                "KWD": float(rates.get("KWD", 0)),
                "EUR": float(rates.get("EUR", 0)),
            },
            "source": "frankfurter",
            "timestamp": int(now),
        }

        for currency in SUPPORTED_CURRENCIES:
            if payload["rates"].get(currency, 0) <= 0:
                raise ValueError(f"Missing FX rate for {currency}")

        _fx_cache["timestamp"] = now
        _fx_cache["payload"] = payload
        return payload
    except Exception as exc:
        print(f"FX rate fetch failed: {exc}")
        if cached_payload:
            return cached_payload

        return {
            "base": "USD",
            "rates": FALLBACK_FX_RATES,
            "source": "fallback",
            "timestamp": int(now),
        }

# --- Wallet ---
@app.post("/api/wallet/transaction")
def wallet_transaction(portfolio_id: int, type: str, amount: float, session: Session = Depends(get_session)):
    get_portfolio_or_404(session, portfolio_id)

    txn_type = (type or "").strip().upper()
    if txn_type not in {"DEPOSIT", "WITHDRAW"}:
        raise HTTPException(status_code=400, detail="Invalid transaction type")
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be greater than 0")

    if txn_type == "WITHDRAW":
        cash_balance = get_cash_balance(session, portfolio_id)
        if amount - cash_balance > 1e-8:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient cash. Available: ${cash_balance:.2f}, Requested: ${amount:.2f}"
            )

    txn = WalletTransaction(portfolio_id=portfolio_id, type=txn_type, amount=amount)
    session.add(txn)
    session.commit()

    return {
        "status": "success",
        "txn_id": txn.id,
        "cash_balance": get_cash_balance(session, portfolio_id),
    }

# --- Trades ---
@app.post("/api/trades")
def add_trade(portfolio_id: int, coin_id: str, symbol: str, type: str, price: float, quantity: float, fee: float = 0.0, fee_type: str = "FIXED", target_lot_id: Optional[int] = Query(None), session: Session = Depends(get_session)):
    get_portfolio_or_404(session, portfolio_id)

    trade_type = (type or "").strip().upper()
    normalized_fee_type = (fee_type or "").strip().upper()

    if trade_type not in {"BUY", "SELL"}:
        raise HTTPException(status_code=400, detail="Invalid trade type")
    if normalized_fee_type not in {"FIXED", "PERCENTAGE"}:
        raise HTTPException(status_code=400, detail="Invalid fee type")
    if price <= 0 or quantity <= 0 or fee < 0:
        raise HTTPException(status_code=400, detail="Price and quantity must be positive and fee cannot be negative")

    # For percentage fees we store fee as percentage input and derive fee value from units.
    # fee_units = quantity * (percentage / 100)
    # fee_value = fee_units * price
    stored_fee = fee
    fee_value = get_fee_value(price, quantity, fee, normalized_fee_type)

    total_val = price * quantity
    if trade_type == "BUY":
        cash_required = get_buy_cash_required(total_val, fee_value, normalized_fee_type)
        cash_balance = get_cash_balance(session, portfolio_id)
        if cash_required - cash_balance > 1e-8:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient cash. Available: ${cash_balance:.2f}, Required: ${cash_required:.2f}"
            )

    # 1. Record Trade
    trade = Trade(
        portfolio_id=portfolio_id,
        target_lot_id=target_lot_id,
        coin_id=coin_id,
        symbol=symbol,
        type=trade_type, # BUY/SELL
        price=price,
        quantity=quantity,
        fee=stored_fee,
        fee_type=normalized_fee_type
    )
    session.add(trade)
    session.commit()
    session.refresh(trade)
    
    # 2. Lot Logic (FIFO)
    lot_manager = LotManager(session)
    realized_pnl = 0.0
    
    try:
        if trade_type == "BUY":
            lot_manager.process_buy(trade)
        elif trade_type == "SELL":
            realized_pnl = lot_manager.process_sell(trade)
    except ValueError as e:
        session.delete(trade) # Rollback trade if lot logic fails
        session.commit()
        raise HTTPException(status_code=400, detail=str(e))
            
    # 3. Update Cash Balance
    # For BUY:
    # - FIXED fee: cash = total value + fee value
    # - PERCENTAGE fee on units: cash = total value (fee is deducted from units)
    # For SELL: cash = total value - fee value
    
    cash_change = 0.0
    
    if trade_type == "BUY":
        cash_change = -get_buy_cash_required(total_val, fee_value, normalized_fee_type)
    else:
        cash_change = (total_val - fee_value)
        
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


@app.patch("/api/trades/{trade_id}")
def update_buy_trade(
    trade_id: int,
    portfolio_id: int,
    price: float,
    quantity: float,
    fee: float = 0.0,
    fee_type: str = "FIXED",
    session: Session = Depends(get_session)
):
    if price <= 0 or quantity <= 0 or fee < 0:
        raise HTTPException(status_code=400, detail="Price and quantity must be positive and fee cannot be negative")
    normalized_fee_type = (fee_type or "").strip().upper()
    if normalized_fee_type not in {"FIXED", "PERCENTAGE"}:
        raise HTTPException(status_code=400, detail="Invalid fee type")

    trade = session.exec(
        select(Trade)
        .where(Trade.id == trade_id)
        .where(Trade.portfolio_id == portfolio_id)
    ).first()

    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")

    if trade.type != TradeType.BUY:
        raise HTTPException(status_code=400, detail="Only BUY trades can be edited")

    lot = session.exec(select(TaxLot).where(TaxLot.trade_id == trade.id)).first()
    if not lot:
        raise HTTPException(status_code=404, detail="Tax lot not found for this trade")

    # Prevent editing lots that were partially closed because realized P/L history
    # for already-closed chunks would become inconsistent.
    if abs(lot.remaining_qty - lot.original_qty) > 1e-8:
        raise HTTPException(status_code=400, detail="This lot is partially sold and cannot be edited")

    new_fee_value = get_fee_value(price, quantity, fee, normalized_fee_type)
    old_fee_type = normalize_fee_type(trade.fee_type)
    old_fee_value = get_fee_value(trade.price, trade.quantity, trade.fee or 0.0, old_fee_type)

    current_cash = get_cash_balance(session, portfolio_id)

    old_total_val = trade.price * trade.quantity
    new_total_val = price * quantity

    old_cash_change = -get_buy_cash_required(old_total_val, old_fee_value, old_fee_type)
    new_cash_change = -get_buy_cash_required(new_total_val, new_fee_value, normalized_fee_type)
    cash_delta = new_cash_change - old_cash_change

    if cash_delta < 0 and (current_cash + cash_delta) < -1e-8:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient cash for edit. Available: ${current_cash:.2f}, Additional required: ${abs(cash_delta):.2f}"
        )

    trade.price = price
    trade.quantity = quantity
    trade.fee = fee
    trade.fee_type = normalized_fee_type

    net_quantity = get_buy_net_quantity(quantity, fee, normalized_fee_type)
    if net_quantity <= 0:
        raise HTTPException(status_code=400, detail="Fee is too high. Net BUY units must be greater than 0.")

    lot.original_qty = net_quantity
    lot.remaining_qty = net_quantity
    lot.cost_basis = price

    session.add(trade)
    session.add(lot)

    # Keep wallet balance consistent after historical trade edits.
    if abs(cash_delta) > 1e-8:
        wallet_txn = WalletTransaction(
            portfolio_id=portfolio_id,
            type="DEPOSIT" if cash_delta > 0 else "WITHDRAW",
            amount=abs(cash_delta),
            timestamp=datetime.utcnow(),
        )
        session.add(wallet_txn)

    session.commit()

    return {
        "status": "success",
        "trade_id": trade.id,
        "lot_id": lot.id,
        "price": trade.price,
        "quantity": trade.quantity,
        "fee": trade.fee,
        "fee_value": get_fee_value(trade.price, trade.quantity, trade.fee or 0.0, normalize_fee_type(trade.fee_type)),
    }

@app.get("/api/trades", response_model=List[Trade])
def get_trades(portfolio_id: int, session: Session = Depends(get_session)):
    get_portfolio_or_404(session, portfolio_id)
    trades = session.exec(select(Trade).where(Trade.portfolio_id == portfolio_id).order_by(Trade.timestamp.desc())).all()
    return trades

@app.get("/api/portfolio/{portfolio_id}/positions/{coin_id}")
def get_position_detail(portfolio_id: int, coin_id: str, session: Session = Depends(get_session)):
    """Fetch metrics for a specific coin in a portfolio, even if balance is zero."""
    get_portfolio_or_404(session, portfolio_id)
    calc = Calculator(session)
    return calc.get_position_detail(portfolio_id, coin_id)

@app.get("/api/portfolio/{portfolio_id}/positions/{coin_id}/lots")
def get_position_lots(portfolio_id: int, coin_id: str, session: Session = Depends(get_session)):
    """Fetch all open tax lots for a specific coin in a portfolio."""
    get_portfolio_or_404(session, portfolio_id)
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
            "fee_type": normalize_fee_type(lot.trade.fee_type),
            "fee_units": get_fee_units(lot.trade.quantity, lot.trade.fee or 0.0, normalize_fee_type(lot.trade.fee_type)),
            "fee_value": get_fee_value(lot.trade.price, lot.trade.quantity, lot.trade.fee or 0.0, normalize_fee_type(lot.trade.fee_type)),
            "timestamp": lot.timestamp
        }
        for lot in lots
    ]

# --- Dashboard & Positions (Calculated View) ---
@app.get("/api/portfolio/{portfolio_id}/positions")
def get_positions(portfolio_id: int, session: Session = Depends(get_session)):
    get_portfolio_or_404(session, portfolio_id)
    calc = Calculator(session)
    return calc.get_positions(portfolio_id)

@app.get("/api/portfolio/{portfolio_id}/summary")
def get_summary(portfolio_id: int, session: Session = Depends(get_session)):
    get_portfolio_or_404(session, portfolio_id)
    calc = Calculator(session)

    cash_balance = get_cash_balance(session, portfolio_id)
    
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
