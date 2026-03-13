from typing import List, Tuple
from sqlmodel import Session, select
from models import Trade, TaxLot, LotClosure, TradeType
from decimal import Decimal, getcontext

# Set precision
getcontext().prec = 28

class LotManager:
    def __init__(self, session: Session):
        self.session = session

    def _normalize_fee_type(self, fee_type) -> str:
        raw = fee_type.value if hasattr(fee_type, "value") else str(fee_type or "")
        return raw.strip().upper()

    def process_buy(self, trade: Trade):
        """Creates a new TaxLot for a Buy trade."""
        # GROSS logic: Cost basis is just the trade price. Fees are tracked separately.
        cost_basis_per_unit = Decimal(str(trade.price))

        qty = Decimal(str(trade.quantity))
        net_qty = qty

        if self._normalize_fee_type(trade.fee_type) == "PERCENTAGE":
            fee_percent = Decimal(str(trade.fee or 0.0))
            fee_units = qty * (fee_percent / Decimal("100"))
            net_qty = qty - fee_units

        if net_qty <= Decimal("0"):
            raise ValueError("Fee is too high. Net BUY units must be greater than 0.")
        
        lot = TaxLot(
            trade_id=trade.id,
            original_qty=float(net_qty),
            remaining_qty=float(net_qty),
            cost_basis=float(cost_basis_per_unit),
            timestamp=trade.timestamp
        )
        self.session.add(lot)
        self.session.commit()

    def process_sell(self, trade: Trade) -> float:
        """
        Processes a Sell trade using STRICT FIFO.
        Returns the total Realized PnL.
        """
        # Fetch detailed lots (FIFO = Oldest First, unless target_lot_id is set)
        statement = (
            select(TaxLot)
            .join(Trade)
            .where(Trade.portfolio_id == trade.portfolio_id)
            .where(Trade.coin_id == trade.coin_id)
            .where(TaxLot.remaining_qty > 0)
        )

        if trade.target_lot_id:
            statement = statement.where(TaxLot.id == trade.target_lot_id)
        else:
            statement = statement.order_by(TaxLot.timestamp.asc()) # STRICT FIFO
        
        available_lots = self.session.exec(statement).all()

        qty_to_sell = Decimal(str(trade.quantity))
        total_realized_pnl = Decimal("0.0")
        sell_price = Decimal(str(trade.price))

        # Fee for sell reduces proceeds
        # Proceeds = (Sell Price * Qty) - Fee
        # Realized PnL = Proceeds - Cost Basis of Lots
        
        # We need to allocate the Sell Fee proportionally to each closed lot to get accurate PnL per closure?
        # Or just subtract total fee from total PnL at the end? 
        # Let's subtract from total PnL at end to simplify lot math.
        
        for lot in available_lots:
            if qty_to_sell <= Decimal("0"):
                break

            lot_remaining = Decimal(str(lot.remaining_qty))
            take_qty = min(lot_remaining, qty_to_sell)
            
            lot_cost = Decimal(str(lot.cost_basis))
            
            # PnL for this chunk (Gross, before sell fees)
            chunk_pnl = (sell_price - lot_cost) * take_qty
            total_realized_pnl += chunk_pnl

            # Update Lot
            new_remaining = lot_remaining - take_qty
            lot.remaining_qty = float(new_remaining)
            qty_to_sell -= take_qty
            
            # Record Closure
            closure = LotClosure(
                sell_trade_id=trade.id,
                tax_lot_id=lot.id,
                quantity=float(take_qty),
                realized_pnl=float(chunk_pnl) 
            )
            self.session.add(closure)
            self.session.add(lot) 

        if qty_to_sell > Decimal("1e-8"): # Floating point tolerance
            raise ValueError(f"Insufficient holdings. Missing {qty_to_sell} units.")

        # Save Gross Realized PnL to the trade
        trade.realized_pnl = float(total_realized_pnl)
        self.session.add(trade)

        self.session.commit()
        return float(total_realized_pnl)
