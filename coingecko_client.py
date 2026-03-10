import requests
import time
from typing import Optional, Dict, Any, List

import os

class CoinGeckoClient:
    def __init__(self):
        self._api_key = os.getenv("COINGECKO_API_KEY")
        self._is_pro = os.getenv("COINGECKO_PRO", "false").lower() == "true"
        
        if self._is_pro:
            self.BASE_URL = "https://pro-api.coingecko.com/api/v3"
            self._min_interval = 0.5 # Higher limit for Pro
        elif self._api_key:
            self.BASE_URL = "https://api.coingecko.com/api/v3"
            self._min_interval = 5.0 # Better limit with key
        else:
            self.BASE_URL = "https://api.coingecko.com/api/v3"
            self._min_interval = 20.0 # Strict throttling for free
            
    _cache = {}
    _last_request_time = 0

    def _get_headers(self) -> Dict[str, str]:
        headers = {}
        if self._api_key:
            if self._is_pro:
                headers["x-cg-pro-api-key"] = self._api_key
            else:
                headers["x-cg-demo-api-key"] = self._api_key
        return headers

    def _wait_for_rate_limit(self):
        elapsed = time.time() - CoinGeckoClient._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        CoinGeckoClient._last_request_time = time.time()

    def get_price(self, coin_ids: str, currency: str = "usd") -> Dict[str, Any]:
        """IDs comma separated. Checks internal cache first."""
        now = time.time()
        
        cache_key = f"price_{coin_ids}_{currency}"
        cached = self._cache.get(cache_key)
        
        if cached and (now - cached['timestamp'] < 20):
            return cached['data']
            
        self._wait_for_rate_limit()
        try:
            url = f"{self.BASE_URL}/simple/price?ids={coin_ids}&vs_currencies={currency}&include_24hr_change=true"
            response = requests.get(url, headers=self._get_headers(), timeout=5)
            if response.status_code == 200:
                data = response.json()
                self._cache[cache_key] = {"timestamp": now, "data": data}
                return data
        except Exception as e:
            print(f"CoinGecko Error: {e}")
            if cached: return cached['data']
            
        return {}

    def search_coins(self, query: str, limit: int = 6) -> List[Dict[str, Any]]:
        """Search for coins by name/symbol, returns results with prices."""
        now = time.time()
        
        cache_key = f"search_{query.lower()}"
        cached = self._cache.get(cache_key)
        if cached and (now - cached['timestamp'] < 60):
            return cached['data']

        self._wait_for_rate_limit()
        try:
            url = f"{self.BASE_URL}/search?query={query}"
            response = requests.get(url, headers=self._get_headers(), timeout=5)
            if response.status_code != 200:
                return cached['data'] if cached else []
            
            coins = response.json().get("coins", [])[:limit]
            if not coins:
                return []

            # Batch fetch prices for results
            coin_ids = ",".join(c["id"] for c in coins)
            prices = self.get_price(coin_ids)

            results = []
            for c in coins:
                price_data = prices.get(c["id"], {})
                results.append({
                    "id": c["id"],
                    "name": c["name"],
                    "symbol": c["symbol"].upper(),
                    "thumb": c.get("thumb", ""),
                    "price_usd": price_data.get("usd"),
                    "change_24h": price_data.get("usd_24h_change"),
                })
            
            self._cache[cache_key] = {"timestamp": now, "data": results}
            return results
        except Exception as e:
            print(f"CoinGecko Search Error: {e}")
            if cached: return cached['data']
            return []

    def get_ohlc(self, coin_id: str, days: int = 7, currency: str = "usd") -> List[Dict[str, Any]]:
        """Get OHLC candlestick data for a coin. Returns list of {time, open, high, low, close}."""
        now = time.time()
        
        cache_key = f"ohlc_{coin_id}_{days}_{currency}"
        cached = self._cache.get(cache_key)
        if cached and (now - cached['timestamp'] < 60):
            return cached['data']

        self._wait_for_rate_limit()
        try:
            url = f"{self.BASE_URL}/coins/{coin_id}/ohlc?vs_currency={currency}&days={days}"
            response = requests.get(url, headers=self._get_headers(), timeout=10)
            if response.status_code != 200:
                return cached['data'] if cached else []
            
            raw = response.json()
            # CoinGecko returns [[timestamp_ms, open, high, low, close], ...]
            results = []
            for candle in raw:
                results.append({
                    "time": int(candle[0] / 1000),  # Convert ms to seconds for lightweight-charts
                    "open": candle[1],
                    "high": candle[2],
                    "low": candle[3],
                    "close": candle[4],
                })
            
            self._cache[cache_key] = {"timestamp": now, "data": results}
            return results
        except Exception as e:
            print(f"CoinGecko OHLC Error: {e}")
            if cached: return cached['data']
            return []
