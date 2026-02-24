"""
Ethereum Wallet Tracker - Data Collection Script
Fetches full transaction history from Etherscan API and calculates running balance.
Usage:
  Initial:  python collect_data.py --full
  Daily:    python collect_data.py --update
"""

import requests
import json
import time
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# ============================================================
# CONFIG
# ============================================================
ETHERSCAN_API_KEY = os.environ.get("ETHERSCAN_API_KEY", "YourApiKeyToken")
BASE_URL = "https://api.etherscan.io/v2/api"
DATA_DIR = Path("data")
RATE_LIMIT_DELAY = 0.25  # 4 req/sec (stay under 5/sec free limit)

WALLETS = {
    "vitalik_main": {
        "address": "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",
        "label": "Vitalik (vitalik.eth)",
        "group": "vitalik"
    },
    "vitalik_vb": {
        "address": "0xAb5801a7D398351b8bE11C439e05C5B3259aeC9B",
        "label": "Vitalik (Vb)",
        "group": "vitalik"
    },
    "vitalik_vb3": {
        "address": "0x220866B1A2219f40e72f5c628B65D54268Ca3A9D",
        "label": "Vitalik (Vb3)",
        "group": "vitalik"
    },
    "vitalik_safe": {
        "address": "0xfEB016D0D14AC0Fa6d69199608B0776d007203B2",
        "label": "Vitalik (Gnosis Safe)",
        "group": "vitalik"
    },
    "ef_multisig": {
        "address": "0xde0B295669a9FD93d5F28D9Ec85E40f4cb697BAe",
        "label": "Ethereum Foundation (Multisig)",
        "group": "ef"
    },
    "ef_1": {
        "address": "0x5eD8Cee6b63b1c6AFce3AD7c92f4fD7E1B8fAd9F",
        "label": "Ethereum Foundation (EF 1)",
        "group": "ef"
    },
    "ef_ens": {
        "address": "0x561b0145d8f5221995bc6A787D8D70Db0604b7B8",
        "label": "Ethereum Foundation (ENS)",
        "group": "ef"
    }
}

# WETH contract address (for tracking WETH token swaps as sell events)
WETH_ADDRESS = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"

# Known exchange deposit addresses (for sell detection)
KNOWN_ADDRESSES = {
    # Exchanges
    "0x28c6c06298d514db089934071355e5743bf21d60": "Binance",
    "0x21a31ee1afc51d94c2efccaa2092ad1028285549": "Binance",
    "0xdfd5293d8e347dfe59e90efd55b2956a1343963d": "Binance",
    "0x56eddb7aa87536c09ccc2793473599fd21a8b17f": "Binance",
    "0x9696f59e4d72e237be84ffd425dcad154bf96976": "Binance",
    "0x4976a4a02f38326660d17bf34b431dc6e2eb2327": "Binance",
    "0x267be1c1d684f78cb4f6a176c4911b741e4ffdc0": "Kraken",
    "0xae2d4617c862309a3d75a0ffb358c7a5009c673f": "Kraken",
    "0x0a869d79a7052c7f1b55a8ebabbea3420f0d1e13": "Kraken",
    "0xe853c56864a2ebe4576a807d26fdc4a0ada51919": "Kraken",
    "0x2910543af39aba0cd09dbb2d50200b3e800a63d2": "Kraken",
    "0xdc76cd25977e0a5ae17155770273ad58648900d3": "Coinbase",
    "0x503828976d22510aad0201ac7ec88293211d23da": "Coinbase",
    "0x71660c4005ba85c37ccec55d0c4493e66fe775d3": "Coinbase",
    "0xa090e606e30bd747d4e6245a1517ebe430f0057e": "Coinbase",
    "0x77134cbc06cb00b66f4c7e623d5fdbf6777635ec": "Coinbase",
    # DEX Protocols
    "0x9008d19f58aabd9ed0d60971565aa8510560ab41": "CoW Protocol",
    "0x3fc91a3afd70395cd496c647d5a6cc9d4b2b7fad": "Uniswap Universal Router",
    "0x7a250d5630b4cf539739df2c5dacb4c659f2488d": "Uniswap V2 Router",
    "0xe592427a0aece92de3edee1f18e0157c05861564": "Uniswap V3 Router",
    "0xdef1c0ded9bec7f1a1670819833240f027b25eff": "0x Exchange",
    "0x1111111254eeb25477b68fb85ed929f73a960582": "1inch Router",
    "0x881d40237659c251811cec9c364ef91dc08d300c": "Metamask Swap",
}


def etherscan_get(params, retries=3):
    """Make Etherscan API call with rate limiting and retries."""
    params["apikey"] = ETHERSCAN_API_KEY
    params["chainid"] = 1
    for attempt in range(retries):
        try:
            time.sleep(RATE_LIMIT_DELAY)
            resp = requests.get(BASE_URL, params=params, timeout=30)
            data = resp.json()
            if data.get("status") == "1" or data.get("message") == "No transactions found":
                return data.get("result", [])
            if "rate limit" in str(data.get("message", "")).lower():
                print(f"  Rate limited, waiting 2s...")
                time.sleep(2)
                continue
            print(f"  API warning: {data.get('message', 'unknown')}")
            return data.get("result", [])
        except Exception as e:
            print(f"  Request error (attempt {attempt+1}): {e}")
            time.sleep(2)
    return []


def fetch_all_transactions(address, start_block=0):
    """Fetch all normal + internal transactions for an address (paginated)."""
    all_txs = []

    # Normal transactions
    print(f"  Fetching normal transactions from block {start_block}...")
    page = 1
    while True:
        txs = etherscan_get({
            "module": "account",
            "action": "txlist",
            "address": address,
            "startblock": start_block,
            "endblock": 99999999,
            "page": page,
            "offset": 10000,
            "sort": "asc"
        })
        if not txs or not isinstance(txs, list):
            break
        for tx in txs:
            tx["_type"] = "normal"
        all_txs.extend(txs)
        print(f"    Page {page}: {len(txs)} txs (total: {len(all_txs)})")
        if len(txs) < 10000:
            break
        page += 1

    # Internal transactions
    print(f"  Fetching internal transactions from block {start_block}...")
    page = 1
    while True:
        txs = etherscan_get({
            "module": "account",
            "action": "txlistinternal",
            "address": address,
            "startblock": start_block,
            "endblock": 99999999,
            "page": page,
            "offset": 10000,
            "sort": "asc"
        })
        if not txs or not isinstance(txs, list):
            break
        for tx in txs:
            tx["_type"] = "internal"
        all_txs.extend(txs)
        print(f"    Page {page}: {len(txs)} internal txs")
        if len(txs) < 10000:
            break
        page += 1

    # WETH token transfers (for detecting DEX swaps like CoW Protocol)
    print(f"  Fetching WETH token transfers from block {start_block}...")
    page = 1
    while True:
        txs = etherscan_get({
            "module": "account",
            "action": "tokentx",
            "contractaddress": WETH_ADDRESS,
            "address": address,
            "startblock": start_block,
            "endblock": 99999999,
            "page": page,
            "offset": 10000,
            "sort": "asc"
        })
        if not txs or not isinstance(txs, list):
            break
        for tx in txs:
            tx["_type"] = "weth_transfer"
        all_txs.extend(txs)
        print(f"    Page {page}: {len(txs)} WETH transfers")
        if len(txs) < 10000:
            break
        page += 1

    # Sort by timestamp
    all_txs.sort(key=lambda x: int(x.get("timeStamp", 0)))
    return all_txs


def process_transactions(address, txs):
    """
    Process transactions to calculate:
    - Running ETH balance over time (daily snapshots)
    - Sell events (large outflows to exchanges or large outflows in general)
    """
    address_lower = address.lower()
    balance_wei = 0
    daily_balances = {}  # date_str -> balance_eth
    sell_events = []

    for tx in txs:
        ts = int(tx.get("timeStamp", 0))
        value_wei = int(tx.get("value", 0))
        from_addr = tx.get("from", "").lower()
        to_addr = tx.get("to", "").lower()
        is_error = tx.get("isError", "0") == "1"

        if is_error and tx.get("_type") == "normal":
            continue

        # WETH transfers don't affect native ETH balance - only track as sell events
        if tx.get("_type") == "weth_transfer":
            date_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
            # Detect WETH outgoing transfers as sell events (DEX swaps)
            if from_addr == address_lower and value_wei > 10 * 1e18:
                eth_amount = value_wei / 1e18
                dest = KNOWN_ADDRESSES.get(to_addr, None)
                tx_hash = tx.get("hash", "")
                if not any(s["tx_hash"] == tx_hash for s in sell_events):
                    sell_events.append({
                        "date": date_str,
                        "timestamp": ts,
                        "amount_eth": round(eth_amount, 4),
                        "to": to_addr,
                        "exchange": dest or "DEX Swap (WETH)",
                        "tx_hash": tx_hash,
                        "type": "weth_swap"
                    })
            continue  # Don't modify ETH balance

        # Gas cost (only for normal outgoing txs)
        gas_cost = 0
        if tx.get("_type") == "normal" and from_addr == address_lower:
            gas_used = int(tx.get("gasUsed", 0))
            gas_price = int(tx.get("gasPrice", 0))
            gas_cost = gas_used * gas_price

        # Update balance
        if from_addr == address_lower and to_addr == address_lower:
            # Self transfer, only gas
            balance_wei -= gas_cost
        elif from_addr == address_lower:
            balance_wei -= value_wei + gas_cost
        elif to_addr == address_lower:
            balance_wei += value_wei

        # Daily snapshot
        date_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        balance_eth = balance_wei / 1e18
        daily_balances[date_str] = round(balance_eth, 4)

        # Detect sell events (outgoing > 10 ETH)
        if from_addr == address_lower and value_wei > 10 * 1e18:
            eth_amount = value_wei / 1e18
            dest = KNOWN_ADDRESSES.get(to_addr, None)
            sell_events.append({
                "date": date_str,
                "timestamp": ts,
                "amount_eth": round(eth_amount, 4),
                "to": to_addr,
                "exchange": dest,
                "tx_hash": tx.get("hash", ""),
                "type": "known_dest" if dest else "large_outflow"
            })

    return daily_balances, sell_events


def get_current_balance(address):
    """Get current ETH balance from API."""
    result = etherscan_get({
        "module": "account",
        "action": "balance",
        "address": address,
        "tag": "latest"
    })
    if result and isinstance(result, str):
        return int(result) / 1e18
    return 0


def load_eth_prices_from_csv():
    """Load historical ETH prices from CSV file."""
    csv_path = DATA_DIR / "ETH_USD.csv"
    if not csv_path.exists():
        # Try parent directory
        csv_path = Path("ETH_USD.csv")
    if not csv_path.exists():
        print("  ETH_USD.csv not found, skipping CSV prices")
        return {}
    
    prices = {}
    with open(csv_path, "r") as f:
        header = True
        for line in f:
            if header:
                header = False
                continue
            parts = line.strip().split(",")
            if len(parts) >= 2:
                date_str = parts[0].strip()
                try:
                    close_price = float(parts[1])
                    prices[date_str] = round(close_price, 2)
                except (ValueError, IndexError):
                    continue
    print(f"  Loaded {len(prices)} prices from CSV")
    return prices


def fetch_eth_price_today():
    """Fetch current ETH price from Etherscan API (reliable, uses existing API key)."""
    print("Fetching current ETH price from Etherscan...")
    try:
        result = etherscan_get({
            "module": "stats",
            "action": "ethprice"
        })
        if result and isinstance(result, dict):
            usd_price = float(result.get("ethusd", 0))
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            print(f"  Current ETH price: ${usd_price}")
            return {today: round(usd_price, 2)}
    except Exception as e:
        print(f"  Failed to fetch price: {e}")
    return {}


def run_full_collection():
    """Initial full data collection for all wallets."""
    DATA_DIR.mkdir(exist_ok=True)
    all_data = {}

    for wallet_id, wallet_info in WALLETS.items():
        address = wallet_info["address"]
        print(f"\n{'='*60}")
        print(f"Processing: {wallet_info['label']}")
        print(f"Address: {address}")
        print(f"{'='*60}")

        txs = fetch_all_transactions(address)
        print(f"  Total transactions: {len(txs)}")

        daily_balances, sell_events = process_transactions(address, txs)
        current_balance = get_current_balance(address)

        # Fix for genesis/pre-mine allocations not captured in txlist
        # Calculate offset between actual balance and calculated balance
        if daily_balances:
            sorted_dates = sorted(daily_balances.keys())
            calculated_final = daily_balances[sorted_dates[-1]]
            offset = current_balance - calculated_final
            if abs(offset) > 1:  # Significant difference = missing initial balance
                print(f"  Balance offset detected: {offset:.4f} ETH (genesis/initial allocation)")
                for date_str in daily_balances:
                    daily_balances[date_str] = round(daily_balances[date_str] + offset, 4)

        print(f"  Daily snapshots: {len(daily_balances)}")
        print(f"  Sell events (>10 ETH): {len(sell_events)}")
        print(f"  Current balance: {current_balance:.4f} ETH")

        # Get last block number for incremental updates
        last_block = 0
        if txs:
            last_block = max(int(tx.get("blockNumber", 0)) for tx in txs)

        all_data[wallet_id] = {
            "info": wallet_info,
            "daily_balances": daily_balances,
            "sell_events": sell_events,
            "current_balance": round(current_balance, 4),
            "last_block": last_block,
            "last_updated": datetime.now(timezone.utc).isoformat()
        }

    # Fetch ETH prices: CSV history + today from Etherscan
    eth_prices = load_eth_prices_from_csv()
    today_price = fetch_eth_price_today()
    eth_prices.update(today_price)

    # Calculate group totals (vitalik combined, ef combined)
    group_balances = {"vitalik": {}, "ef": {}}
    group_sells = {"vitalik": [], "ef": []}

    for wallet_id, wdata in all_data.items():
        group = wdata["info"]["group"]
        for date_str, bal in wdata["daily_balances"].items():
            group_balances[group][date_str] = group_balances[group].get(date_str, 0) + bal
        group_sells[group].extend(wdata["sell_events"])

    # Round group balances
    for group in group_balances:
        for date_str in group_balances[group]:
            group_balances[group][date_str] = round(group_balances[group][date_str], 4)

    # Build chart data
    chart_data = {
        "wallets": all_data,
        "groups": {
            "vitalik": {
                "daily_balances": dict(sorted(group_balances["vitalik"].items())),
                "sell_events": sorted(group_sells["vitalik"], key=lambda x: x["timestamp"])
            },
            "ef": {
                "daily_balances": dict(sorted(group_balances["ef"].items())),
                "sell_events": sorted(group_sells["ef"], key=lambda x: x["timestamp"])
            }
        },
        "eth_prices": eth_prices,
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "mode": "full"
        }
    }

    output_path = DATA_DIR / "wallet_data.json"
    with open(output_path, "w") as f:
        json.dump(chart_data, f, indent=2)
    print(f"\nData saved to {output_path}")
    print(f"File size: {output_path.stat().st_size / 1024:.1f} KB")


def run_update():
    """Incremental update - fetch only new transactions since last block."""
    data_path = DATA_DIR / "wallet_data.json"
    if not data_path.exists():
        print("No existing data found. Run with --full first.")
        sys.exit(1)

    with open(data_path) as f:
        chart_data = json.load(f)

    for wallet_id, wallet_info in WALLETS.items():
        address = wallet_info["address"]
        existing = chart_data["wallets"].get(wallet_id, {})
        last_block = existing.get("last_block", 0)

        print(f"\nUpdating: {wallet_info['label']} (from block {last_block})")

        txs = fetch_all_transactions(address, start_block=last_block + 1)

        if txs:
            print(f"  New transactions: {len(txs)}")
            new_balances, new_sells = process_transactions(address, txs)
            existing_balances = existing.get("daily_balances", {})
            existing_balances.update(new_balances)
            existing["daily_balances"] = existing_balances

            existing_sells = existing.get("sell_events", [])
            existing_sells.extend(new_sells)
            existing["sell_events"] = existing_sells

            new_last_block = max(int(tx.get("blockNumber", 0)) for tx in txs)
            existing["last_block"] = max(last_block, new_last_block)
        else:
            print("  No new transactions")

        # ALWAYS re-apply offset correction using current actual balance
        current_balance = get_current_balance(address)
        existing_balances = existing.get("daily_balances", {})
        if existing_balances:
            sorted_dates = sorted(existing_balances.keys())
            calculated_final = existing_balances[sorted_dates[-1]]
            offset = current_balance - calculated_final
            if abs(offset) > 1:
                print(f"  Re-applying offset correction: {offset:.4f} ETH")
                for date_str in existing_balances:
                    existing_balances[date_str] = round(existing_balances[date_str] + offset, 4)
                existing["daily_balances"] = existing_balances

        existing["current_balance"] = round(current_balance, 4)
        existing["last_updated"] = datetime.now(timezone.utc).isoformat()
        chart_data["wallets"][wallet_id] = existing

    # Recalculate group totals
    group_balances = {"vitalik": {}, "ef": {}}
    group_sells = {"vitalik": [], "ef": []}

    for wallet_id, wdata in chart_data["wallets"].items():
        group = wdata["info"]["group"]
        for date_str, bal in wdata["daily_balances"].items():
            group_balances[group][date_str] = group_balances[group].get(date_str, 0) + bal
        group_sells[group].extend(wdata["sell_events"])

    for group in group_balances:
        for date_str in group_balances[group]:
            group_balances[group][date_str] = round(group_balances[group][date_str], 4)

    chart_data["groups"] = {
        "vitalik": {
            "daily_balances": dict(sorted(group_balances["vitalik"].items())),
            "sell_events": sorted(group_sells["vitalik"], key=lambda x: x["timestamp"])
        },
        "ef": {
            "daily_balances": dict(sorted(group_balances["ef"].items())),
            "sell_events": sorted(group_sells["ef"], key=lambda x: x["timestamp"])
        }
    }

    # Backfill ETH prices from CSV if sparse, then add today from Etherscan
    existing_prices = chart_data.get("eth_prices", {})
    if len(existing_prices) < 100:
        print("\n  Prices sparse, backfilling from CSV...")
        csv_prices = load_eth_prices_from_csv()
        csv_prices.update(existing_prices)  # existing overwrites CSV (newer)
        existing_prices = csv_prices

    today_price = fetch_eth_price_today()
    if today_price:
        existing_prices.update(today_price)
    chart_data["eth_prices"] = existing_prices

    chart_data["metadata"]["generated_at"] = datetime.now(timezone.utc).isoformat()
    chart_data["metadata"]["mode"] = "update"

    output_path = DATA_DIR / "wallet_data.json"
    with open(output_path, "w") as f:
        json.dump(chart_data, f, indent=2)
    print(f"\nData updated: {output_path}")


def run_repair():
    """Repair existing data: re-apply offset correction + backfill prices from CSV."""
    data_path = DATA_DIR / "wallet_data.json"
    if not data_path.exists():
        print("No existing data found. Run with --full first.")
        sys.exit(1)

    with open(data_path) as f:
        chart_data = json.load(f)

    print("=== REPAIR MODE ===")

    # 1. Re-apply offset correction for every wallet
    for wallet_id, wdata in chart_data.get("wallets", {}).items():
        address = wdata["info"]["address"]
        label = wdata["info"]["label"]
        daily_balances = wdata.get("daily_balances", {})

        if not daily_balances:
            print(f"\n  {label}: no balance data, skipping")
            continue

        current_balance = get_current_balance(address)
        sorted_dates = sorted(daily_balances.keys())
        calculated_final = daily_balances[sorted_dates[-1]]
        offset = current_balance - calculated_final

        print(f"\n  {label}:")
        print(f"    Actual balance:     {current_balance:.4f} ETH")
        print(f"    Calculated final:   {calculated_final:.4f} ETH")
        print(f"    Offset:             {offset:.4f} ETH")

        if abs(offset) > 0.01:
            for date_str in daily_balances:
                daily_balances[date_str] = round(daily_balances[date_str] + offset, 4)
            print(f"    ✓ Offset applied to {len(daily_balances)} snapshots")

        wdata["daily_balances"] = daily_balances
        wdata["current_balance"] = round(current_balance, 4)

    # 2. Recalculate group totals
    group_balances = {"vitalik": {}, "ef": {}}
    group_sells = {"vitalik": [], "ef": []}

    for wallet_id, wdata in chart_data["wallets"].items():
        group = wdata["info"]["group"]
        for date_str, bal in wdata["daily_balances"].items():
            group_balances[group][date_str] = group_balances[group].get(date_str, 0) + bal
        group_sells[group].extend(wdata.get("sell_events", []))

    for group in group_balances:
        for date_str in group_balances[group]:
            group_balances[group][date_str] = round(group_balances[group][date_str], 4)

    chart_data["groups"] = {
        "vitalik": {
            "daily_balances": dict(sorted(group_balances["vitalik"].items())),
            "sell_events": sorted(group_sells["vitalik"], key=lambda x: x["timestamp"])
        },
        "ef": {
            "daily_balances": dict(sorted(group_balances["ef"].items())),
            "sell_events": sorted(group_sells["ef"], key=lambda x: x["timestamp"])
        }
    }

    # Print group totals for verification
    for g in ["vitalik", "ef"]:
        bals = chart_data["groups"][g]["daily_balances"]
        if bals:
            latest = bals[sorted(bals.keys())[-1]]
            print(f"\n  Group [{g}] latest balance: {latest:.4f} ETH")

    # 3. Backfill prices from CSV
    existing_prices = chart_data.get("eth_prices", {})
    print(f"\n  Existing prices: {len(existing_prices)} entries")

    csv_prices = load_eth_prices_from_csv()
    if csv_prices:
        csv_prices.update(existing_prices)  # keep existing (newer) over CSV
        existing_prices = csv_prices
        print(f"  After CSV backfill: {len(existing_prices)} entries")

    today_price = fetch_eth_price_today()
    if today_price:
        existing_prices.update(today_price)

    chart_data["eth_prices"] = existing_prices

    chart_data["metadata"]["generated_at"] = datetime.now(timezone.utc).isoformat()
    chart_data["metadata"]["mode"] = "repair"

    output_path = DATA_DIR / "wallet_data.json"
    with open(output_path, "w") as f:
        json.dump(chart_data, f, indent=2)
    print(f"\n✓ Repair complete: {output_path}")


if __name__ == "__main__":
    if "--full" in sys.argv:
        run_full_collection()
    elif "--update" in sys.argv:
        run_update()
    elif "--repair" in sys.argv:
        run_repair()
    else:
        print("Usage:")
        print("  python collect_data.py --full    # Initial full collection")
        print("  python collect_data.py --update  # Daily incremental update")
        print("  python collect_data.py --repair  # Fix balances + backfill prices")
