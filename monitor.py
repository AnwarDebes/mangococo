"""
Trade Monitor - Shows buy/sell signals in real-time
Run with: python monitor.py
"""
import redis
import json
import os
from datetime import datetime

# Colors for terminal
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"
BOLD = "\033[1m"

# Redis configuration from environment
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")

def main():
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD, decode_responses=True)
    pubsub = r.pubsub()

    # Subscribe to order updates
    pubsub.subscribe('filled_orders', 'raw_signals')

    print(f"{BOLD}{CYAN}{'='*60}{RESET}")
    print(f"{BOLD}{CYAN}       MANGOCOCO TRADE MONITOR{RESET}")
    print(f"{BOLD}{CYAN}{'='*60}{RESET}")
    print(f"{YELLOW}Watching for trades... Press Ctrl+C to stop{RESET}\n")

    for message in pubsub.listen():
        if message['type'] != 'message':
            continue

        try:
            data = json.loads(message['data'])
            channel = message['channel']
            display_time = datetime.now().strftime("%H:%M:%S")

            if channel == 'filled_orders':
                symbol = data.get('symbol', 'N/A')
                side = data.get('side', 'N/A')
                filled = data.get('filled', 0)
                price = data.get('price', 0)
                cost = data.get('cost', 0)

                if side == 'buy':
                    color = GREEN
                    icon = "BUY "
                else:
                    color = RED
                    icon = "SELL"

                print(f"{color}{BOLD}[{display_time}] {icon} {symbol}{RESET}")
                print(f"{color}   Amount: {filled:.6f} @ ${price:.6f}{RESET}")
                print(f"{color}   Total:  ${cost:.4f} USDT{RESET}")
                print(f"{'-'*40}")

            elif channel == 'raw_signals':
                # Only show if it's a close signal (stop loss / take profit)
                reason = data.get('reason', '')
                if reason in ['stop_loss', 'take_profit', 'max_hold_time']:
                    symbol = data.get('symbol', 'N/A')

                    if reason == 'stop_loss':
                        print(f"{RED}[{display_time}] STOP LOSS triggered: {symbol}{RESET}")
                    elif reason == 'take_profit':
                        print(f"{GREEN}[{display_time}] TAKE PROFIT triggered: {symbol}{RESET}")
                    elif reason == 'max_hold_time':
                        print(f"{YELLOW}[{display_time}] MAX HOLD TIME: {symbol}{RESET}")

        except json.JSONDecodeError:
            pass
        except Exception as e:
            pass

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{YELLOW}Monitor stopped.{RESET}")
    except Exception as e:
        print(f"{RED}Error: {e}{RESET}")
        print(f"{YELLOW}Make sure Redis is running and accessible.{RESET}")
