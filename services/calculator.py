from sqlmodel import Session, select
from models import Trade, TaxLot, LotClosure, TradeType
from decimal import Decimal
from typing import Dict, List, Any
from coingecko_client import CoinGeckoClient

class Calculator:
    def __init__(self, session: Session):
        self.session = session
        self.cg_client = CoinGeckoClient()

    def _trade_fee_value(self, trade: Trade) -> Decimal:
        fee = Decimal(str(trade.fee or 0.0))
        fee_type = (trade.fee_type.value if hasattr(trade.fee_type, "value") else str(trade.fee_type or "")).strip().upper()

        if fee_type == "PERCENTAGE":
            qty = Decimal(str(trade.quantity or 0.0))
            price = Decimal(str(trade.price or 0.0))
            fee_units = qty * (fee / Decimal("100"))
            return fee_units * price

        return fee

    def get_positions(self, portfolio_id: int) -> List[Dict[str, Any]]:
        # 1. Fetch Open Lots
        statement = (
            select(TaxLot)
            .join(Trade)
            .where(Trade.portfolio_id == portfolio_id)
            .where(TaxLot.remaining_qty > 0)
        )
        lots = self.session.exec(statement).all()
        
        # 2. Group by Asset
        assets = {}
        for lot in lots:
            coin_id = lot.trade.coin_id
            symbol = lot.trade.symbol
            
            if coin_id not in assets:
                assets[coin_id] = {
                    "symbol": symbol,
                    "units": Decimal("0"),
                    "invested": Decimal("0"),
                    "fees": Decimal("0"),
                    "current_value": Decimal("0"),
                    "open_lots": 0,
                }
            
            qty = Decimal(str(lot.remaining_qty))
            cost = Decimal(str(lot.cost_basis))
            
            # Pro-rated fee calculation
            orig_qty = Decimal(str(lot.original_qty))
            orig_fee_value = self._trade_fee_value(lot.trade)
            lot_pro_rated_fee = (qty / orig_qty) * orig_fee_value if orig_qty > 0 else Decimal("0")
            
            assets[coin_id]["units"] += qty
            assets[coin_id]["invested"] += (qty * cost)
            assets[coin_id]["fees"] += lot_pro_rated_fee
            assets[coin_id]["open_lots"] += 1

        if not assets:
            return []

        # 3. Fetch Live Prices
        coin_ids = ",".join(assets.keys())
        prices = self.cg_client.get_price(coin_ids)
        
        # 4. Calculate Final Metrics
        results = []
        for coin_id, data in assets.items():
            current_price = Decimal(str(prices.get(coin_id, {}).get("usd", 0)))
            daily_change_pct = Decimal(str(prices.get(coin_id, {}).get("usd_24h_change", 0)))
            
            units = data["units"]
            invested = data["invested"]
            current_val = units * current_price
            
            avg_price = invested / units if units > 0 else 0
            unrealized_pnl = current_val - invested
            pnl_percent = (unrealized_pnl / invested * 100) if invested > 0 else 0
            
            daily_pnl = current_val * (daily_change_pct / 100)

            results.append({
                "id": coin_id,
                "symbol": data["symbol"],
                "open_lots": data["open_lots"],
                "units": float(units),
                "avg_price": float(avg_price),
                "fees": float(data["fees"]),
                "current_price": float(current_price),
                "invested_value": float(invested),
                "current_value": float(current_val),
                "unrealized_pnl": float(unrealized_pnl),
                "pnl_percent": float(pnl_percent),
                "daily_pnl": float(daily_pnl),
                "daily_change_pct": float(daily_change_pct)
            })
            
        return results

    def get_position_detail(self, portfolio_id: int, coin_id: str) -> Dict[str, Any]:
        """Calculates metrics for a single coin, supporting zero-balance views."""
        # 1. Fetch Open Lots
        statement = (
            select(TaxLot)
            .join(Trade)
            .where(Trade.portfolio_id == portfolio_id)
            .where(Trade.coin_id == coin_id)
            .where(TaxLot.remaining_qty > 0)
        )
        lots = self.session.exec(statement).all()
        
        # 2. Derive Symbol (from any trade for this coin if no open lots)
        symbol = "—"
        if lots:
            symbol = lots[0].trade.symbol
        else:
            # Check any trade
            last_trade = self.session.exec(
                select(Trade)
                .where(Trade.portfolio_id == portfolio_id)
                .where(Trade.coin_id == coin_id)
                .order_by(Trade.timestamp.desc())
            ).first()
            if last_trade:
                symbol = last_trade.symbol

        # 3. Aggregate metrics
        units = Decimal("0")
        invested = Decimal("0")
        fees = Decimal("0")
        
        for lot in lots:
            qty = Decimal(str(lot.remaining_qty))
            cost = Decimal(str(lot.cost_basis))
            
            orig_qty = Decimal(str(lot.original_qty))
            orig_fee_value = self._trade_fee_value(lot.trade)
            lot_pro_rated_fee = (qty / orig_qty) * orig_fee_value if orig_qty > 0 else Decimal("0")
            
            units += qty
            invested += (qty * cost)
            fees += lot_pro_rated_fee

        # 4. Live Price
        prices = self.cg_client.get_price(coin_id)
        current_price = Decimal(str(prices.get(coin_id, {}).get("usd", 0)))
        daily_change_pct = Decimal(str(prices.get(coin_id, {}).get("usd_24h_change", 0)))
        
        current_val = units * current_price
        avg_price = invested / units if units > 0 else 0
        unrealized_pnl = current_val - invested
        pnl_percent = (unrealized_pnl / invested * 100) if invested > 0 else 0
        daily_pnl = current_val * (daily_change_pct / 100)

        return {
            "id": coin_id,
            "symbol": symbol,
            "open_lots": len(lots),
            "units": float(units),
            "avg_price": float(avg_price),
            "fees": float(fees),
            "current_price": float(current_price),
            "invested_value": float(invested),
            "current_value": float(current_val),
            "unrealized_pnl": float(unrealized_pnl),
            "pnl_percent": float(pnl_percent),
            "daily_pnl": float(daily_pnl),
            "daily_change_pct": float(daily_change_pct)
        }

    def get_summary(self, portfolio_id: int) -> Dict[str, float]:
        positions = self.get_positions(portfolio_id)
        
        total_invested = sum(p["invested_value"] for p in positions)
        total_current = sum(p["current_value"] for p in positions)
        total_unrealized_pnl = sum(p["unrealized_pnl"] for p in positions)
        total_daily_pnl = sum(p["daily_pnl"] for p in positions)
        
        # Realized PnL from Closed Lots
        closures = self.session.exec(select(LotClosure).join(TaxLot).join(Trade).where(Trade.portfolio_id == portfolio_id)).all()
        total_realized_pnl = sum(c.realized_pnl for c in closures)
        
        total_fees = sum(p["fees"] for p in positions)
        
        return {
            "total_invested": total_invested,
            "total_value": total_current,
            "total_unrealized_pnl": total_unrealized_pnl,
            "total_realized_pnl": total_realized_pnl,
            "total_fees": total_fees,
            "total_pnl": total_unrealized_pnl + total_realized_pnl,
            "daily_pnl": total_daily_pnl
        }
