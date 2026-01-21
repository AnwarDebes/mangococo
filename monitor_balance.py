"""
Balance Monitor - Tracks wallet balance in real-time
Run with: python monitor_balance.py
"""
import requests
import time
import os
from datetime import datetime

# Colors for terminal
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
WHITE = "\033[97m"
DIM = "\033[2m"
RESET = "\033[0m"
BOLD = "\033[1m"

# Clear screen command
CLEAR = "\033[2J\033[H"

def get_balance():
    """Fetch balance from executor service"""
    try:
        response = requests.get("http://localhost:8005/balance", timeout=5)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        return None
    return None


def format_currency(value):
    """Format number as currency"""
    if value >= 1:
        return f"${value:.2f}"
    elif value >= 0.01:
        return f"${value:.4f}"
    else:
        return f"${value:.6f}"

def main():
    print(f"{BOLD}{CYAN}{'='*60}{RESET}")
    print(f"{BOLD}{CYAN}       MANGOCOCO BALANCE MONITOR{RESET}")
    print(f"{BOLD}{CYAN}{'='*60}{RESET}")
    print(f"{YELLOW}Refreshing every 2 seconds... Press Ctrl+C to stop{RESET}\n")

    last_total = None
    last_usdt = None

    while True:
        try:
            # Get current data
            balance_data = get_balance()
            timestamp = datetime.now().strftime("%H:%M:%S")

            if not balance_data:
                print(f"{RED}[{timestamp}] Could not fetch balance - check if services are running{RESET}")
                time.sleep(2)
                continue

            balances = balance_data.get("balances", {})
            is_simulated = balance_data.get("simulated", False)

            # Calculate totals
            usdt_balance = balances.get("USDT", {}).get("free", 0)

            # Build output
            output = []
            output.append(CLEAR)  # Clear screen
            output.append(f"{BOLD}{CYAN}{'='*60}{RESET}")
            output.append(f"{BOLD}{CYAN}       MANGOCOCO BALANCE MONITOR{RESET}")
            output.append(f"{BOLD}{CYAN}{'='*60}{RESET}")
            output.append(f"{DIM}Last updated: {timestamp}{'  [SIMULATED]' if is_simulated else ''}{RESET}\n")

            # USDT Balance with change indicator
            usdt_change = ""
            if last_usdt is not None:
                diff = usdt_balance - last_usdt
                if diff > 0.0001:
                    usdt_change = f" {GREEN}+{format_currency(diff)}{RESET}"
                elif diff < -0.0001:
                    usdt_change = f" {RED}{format_currency(diff)}{RESET}"

            output.append(f"{BOLD}{WHITE}USDT Balance:{RESET} {GREEN}{format_currency(usdt_balance)}{RESET}{usdt_change}")
            output.append("")

            # Other coins
            coin_values = []
            total_value = usdt_balance

            for coin, data in balances.items():
                if coin == "USDT":
                    continue

                amount = data.get("free", 0) + data.get("used", 0)
                if amount < 0.0000001:
                    continue

                # Estimate value (would need price data for accuracy)
                # For now, just show the amount
                coin_values.append((coin, amount))

            if coin_values:
                output.append(f"{BOLD}{WHITE}Other Assets:{RESET}")
                output.append(f"{DIM}{'─'*40}{RESET}")

                for coin, amount in sorted(coin_values, key=lambda x: x[0]):
                    if amount >= 1:
                        output.append(f"  {YELLOW}{coin:8}{RESET} {amount:>15.4f}")
                    else:
                        output.append(f"  {YELLOW}{coin:8}{RESET} {amount:>15.8f}")

            output.append("")
            output.append(f"{DIM}Press Ctrl+C to stop{RESET}")

            # Print all at once (reduces flicker)
            print("\n".join(output))

            # Save for next comparison
            last_usdt = usdt_balance

            time.sleep(2)

        except KeyboardInterrupt:
            print(f"\n{YELLOW}Monitor stopped.{RESET}")
            break
        except Exception as e:
            print(f"{RED}Error: {e}{RESET}")
            time.sleep(2)

if __name__ == "__main__":
    main()
