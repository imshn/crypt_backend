from typing import Optional, List
from datetime import datetime
from sqlmodel import SQLModel, Field, Relationship
from enum import Enum

class TradeType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

class FeeType(str, Enum):
    FIXED = "FIXED"
    PERCENTAGE = "PERCENTAGE"

class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    clerk_id: str = Field(index=True, unique=True)
    email: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    portfolios: List["Portfolio"] = Relationship(back_populates="user")

class Portfolio(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    name: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    user: User = Relationship(back_populates="portfolios")
    interactions: List["WalletTransaction"] = Relationship(back_populates="portfolio")
    trades: List["Trade"] = Relationship(back_populates="portfolio")

class WalletTransaction(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    portfolio_id: int = Field(foreign_key="portfolio.id")
    type: str # DEPOSIT, WITHDRAW
    amount: float
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    
    portfolio: Portfolio = Relationship(back_populates="interactions")

class Trade(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    portfolio_id: int = Field(foreign_key="portfolio.id")
    target_lot_id: Optional[int] = Field(default=None, index=True) # For targeted lot selling
    coin_id: str
    symbol: str
    type: TradeType
    price: float
    quantity: float
    fee: float = Field(default=0.0)
    fee_type: FeeType = Field(default=FeeType.FIXED)
    realized_pnl: Optional[float] = Field(default=None) # Gross Realized PnL for SELL trades
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    
    portfolio: Portfolio = Relationship(back_populates="trades")
    tax_lots: List["TaxLot"] = Relationship(back_populates="trade")
    closures: List["LotClosure"] = Relationship(back_populates="sell_trade")

class TaxLot(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    trade_id: int = Field(foreign_key="trade.id")
    original_qty: float
    remaining_qty: float = Field(index=True)
    cost_basis: float # Unit price including fees
    timestamp: datetime = Field(default_factory=datetime.utcnow) # For FIFO ordering
    
    trade: Trade = Relationship(back_populates="tax_lots")
    closures: List["LotClosure"] = Relationship(back_populates="tax_lot")

class LotClosure(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    sell_trade_id: int = Field(foreign_key="trade.id")
    tax_lot_id: int = Field(foreign_key="taxlot.id")
    quantity: float
    realized_pnl: float
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    
    tax_lot: TaxLot = Relationship(back_populates="closures")
    sell_trade: Trade = Relationship(back_populates="closures")
