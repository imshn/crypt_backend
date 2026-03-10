from sqlmodel import Session, create_engine, select
from models import Trade, TaxLot, TradeType, Portfolio, WalletTransaction
from services.lot_manager import LotManager
from decimal import Decimal
from datetime import datetime

# Setup in-memory DB
engine = create_engine("sqlite:///:memory:")
from sqlmodel import SQLModel
SQLModel.metadata.create_all(engine)

def test_sell_logic():
    with Session(engine) as session:
        # Create portfolio
        p = Portfolio(name="Test", user_id=1)
        session.add(p)
        session.commit()
        session.refresh(p)

        # 1. Buy 0.00025 BTC @ 69111 with 0.173 fee
        buy_trade = Trade(
            portfolio_id=p.id,
            coin_id="bitcoin",
            symbol="BTC",
            type=TradeType.BUY,
            price=69111.0,
            quantity=0.00025,
            fee=0.173,
            timestamp=datetime.utcnow()
        )
        session.add(buy_trade)
        session.commit()
        session.refresh(buy_trade)

        lm = LotManager(session)
        lm.process_buy(buy_trade)
        
        lot = session.exec(select(TaxLot).where(TaxLot.trade_id == buy_trade.id)).one()
        print(f"Lot Created: ID={lot.id}, Qty={lot.remaining_qty}, CostBasis={lot.cost_basis}")
        # Cost basis should be (69111 * 0.00025 + 0.173) / 0.00025 = (17.27775 + 0.173) / 0.00025 = 17.45075 / 0.00025 = 69803.0
        
        # 2. Sell full lot @ 67740 with 0.1 fee
        sell_trade = Trade(
            portfolio_id=p.id,
            coin_id="bitcoin",
            symbol="BTC",
            type=TradeType.SELL,
            price=67740.0,
            quantity=0.00025,
            fee=0.1,
            target_lot_id=lot.id,
            timestamp=datetime.utcnow()
        )
        session.add(sell_trade)
        session.commit()
        session.refresh(sell_trade)
        
        try:
            pnl = lm.process_sell(sell_trade)
            print(f"Sell Success! Realized PnL: {pnl}")
            
            # Verify lot is closed
            session.refresh(lot)
            print(f"Lot Status: Remaining={lot.remaining_qty}")
            
        except Exception as e:
            print(f"Sell Failed: {e}")

if __name__ == "__main__":
    test_sell_logic()
