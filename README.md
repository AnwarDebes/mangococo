# MangoCoco - AI-Powered Crypto Trading Bot

> **⚠️ PROPRIETARY SOFTWARE - ALL RIGHTS RESERVED**
>
> Copyright © 2026. This is private, proprietary software.
>
> **NO LICENSE IS GRANTED.** Unauthorized use, copying, modification, or distribution is strictly prohibited.
>
> See LICENSE file for full terms.

---

MangoCoco is an intelligent cryptocurrency trading bot that uses machine learning to predict market movements and execute trades automatically on MEXC exchange.

**This is a private project for personal use only.**

## Features

- **AI-Powered Predictions**: LSTM neural network for price prediction
- **Real-Time Market Data**: WebSocket streaming from MEXC
- **Risk Management**: Built-in stop-loss, position sizing, and daily loss limits
- **Microservices Architecture**: 8 specialized services for scalability
- **Live Dashboard**: React-based UI for monitoring
- **TimescaleDB**: Optimized time-series data storage
- **Prometheus & Grafana**: Comprehensive monitoring

## System Architecture

```
┌─────────────┐
│  Dashboard  │ (React UI)
└──────┬──────┘
       │
┌──────▼──────────┐
│  API Gateway    │ (Port 8080)
└──────┬──────────┘
       │
       ├──► Market Data Service (Price streaming)
       ├──► Prediction Service (ML predictions)
       ├──► Signal Service (Trade signals)
       ├──► Risk Service (Risk checks)
       ├──► Executor Service (Trade execution)
       └──► Position Service (Portfolio tracking)
```

## Requirements

### Server Requirements
- **OS**: Ubuntu 20.04+ / Debian 11+ / CentOS 8+
- **CPU**: 2+ cores
- **RAM**: 4GB minimum (8GB recommended)
- **Storage**: 20GB free space
- **Network**: Stable internet connection

### Software Requirements
- Docker 20.10+
- Docker Compose 2.0+
- Git

### Trading Requirements
- MEXC account with API access
- Minimum $5 USDT capital (recommended)
- Server IP whitelisted in MEXC API settings

## Quick Start

### 1. Clone Repository

```bash
git clone https://github.com/YOUR_USERNAME/mangococo.git
cd mangococo
```

### 2. Configure Environment

```bash
# Copy example config
cp config/.env.example config/.env

# Edit with your credentials
nano config/.env
```

**Required Settings:**
```env
MEXC_API_KEY=your_api_key_here
MEXC_SECRET_KEY=your_secret_key_here
STARTING_CAPITAL=2.89
```

### 3. Get MEXC API Credentials

1. Login to [MEXC](https://www.mexc.com)
2. Go to **API Management**
3. Click **Create API Key**
4. Enable **Spot Trading** permissions
5. Add your server IP to whitelist
6. Save API Key and Secret Key

### 4. Start the System

```bash
# Create necessary directories
mkdir -p shared/redis-data shared/timescale-data shared/models logs

# Start all services
docker compose up -d --build
```

This will start 12 containers:
- 8 trading services
- Redis (cache)
- TimescaleDB (database)
- Prometheus (metrics)
- Grafana (dashboards)

### 5. Verify Deployment

```bash
# Check all containers are running
docker compose ps

# Check logs
docker compose logs -f

# Test API
curl http://localhost:8080/status
```

Expected output:
```json
{
  "market-data": {"healthy": true},
  "prediction": {"healthy": true},
  "signal": {"healthy": true},
  ...
}
```

### 6. Access Dashboard

Open browser: `http://YOUR_SERVER_IP:3000`

You should see:
- Live price charts
- Portfolio value
- Open positions
- Recent signals
- System status

## Configuration

### Trading Pairs

Edit `config/.env`:
```env
TRADING_PAIRS=BTC/USDT,ETH/USDT,SOL/USDT,BNB/USDT
```

### Risk Settings

```env
MAX_POSITION_PCT=0.50          # Max 50% per position
MIN_POSITION_USD=5.00          # Min $5 per trade
MAX_DAILY_LOSS_PCT=0.20        # Stop at 20% daily loss
MAX_OPEN_POSITIONS=3           # Max 3 concurrent positions
```

### ML Model Settings

```env
SEQUENCE_LENGTH=60              # 60 data points for prediction
PREDICTION_HORIZON=5            # Predict 5 minutes ahead
CONFIDENCE_THRESHOLD=0.65       # Minimum 65% confidence
```

## GPU Support (Optional)

For faster ML predictions, enable GPU support:

1. Install NVIDIA Docker runtime:
```bash
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | \
  sudo tee /etc/apt/sources.list.d/nvidia-docker.list

sudo apt-get update
sudo apt-get install -y nvidia-docker2
sudo systemctl restart docker
```

2. Uncomment GPU section in `docker-compose.yml`:
```yaml
prediction:
  # ...
  deploy:
    resources:
      reservations:
        devices:
          - driver: nvidia
            count: 1
            capabilities: [gpu]
```

3. Set in `.env`:
```env
USE_GPU=true
```

## Monitoring

### Prometheus Metrics
- URL: `http://YOUR_SERVER_IP:9090`
- Metrics: trades, positions, predictions, API calls

### Grafana Dashboards
- URL: `http://YOUR_SERVER_IP:3001`
- Login: `admin` / `admin`
- Pre-configured trading dashboards

### Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f market-data
docker compose logs -f executor

# Follow new logs only
docker compose logs -f --tail=100
```

## API Endpoints

Base URL: `http://localhost:8080`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/status` | GET | System health check |
| `/api/balance` | GET | Account balance |
| `/api/tickers` | GET | Current prices |
| `/api/positions` | GET | Open positions |
| `/api/signals` | GET | Recent signals |
| `/api/predictions` | GET | Latest predictions |
| `/api/trades` | GET | Trade history |

## Troubleshooting

### Containers Won't Start

```bash
# Check logs
docker compose logs

# Restart specific service
docker compose restart market-data

# Rebuild containers
docker compose up -d --build
```

### Connection to MEXC Failed

1. Verify API keys in `config/.env`
2. Check IP whitelist in MEXC settings
3. Test API keys:
```bash
curl -X GET "https://api.mexc.com/api/v3/account" \
  -H "X-MEXC-APIKEY: your_api_key"
```

### Insufficient Capital Errors

```bash
# Check balance
curl http://localhost:8080/api/balance

# Update in .env
STARTING_CAPITAL=10.00
MIN_POSITION_USD=5.00
```

### Prediction Service Crashes (Out of Memory)

Reduce model complexity in `services/prediction/main.py`:
```python
LSTM(32)  # Instead of LSTM(64)
```

Or increase server RAM to 8GB+.

### Database Connection Issues

```bash
# Restart database
docker compose restart timescaledb

# Check database logs
docker compose logs timescaledb

# Reset database (WARNING: deletes all data)
docker compose down -v
docker compose up -d
```

## Maintenance

### Backup

```bash
# Backup database
docker exec mc-timescaledb pg_dump -U mangococo mangococo > backup_$(date +%Y%m%d).sql

# Backup configuration
cp config/.env config/.env.backup
```

### Updates

```bash
# Pull latest code
git pull origin main

# Rebuild and restart
docker compose down
docker compose up -d --build
```

### Clean Up

```bash
# Remove stopped containers
docker compose down

# Remove all data (start fresh)
docker compose down -v
rm -rf shared/redis-data shared/timescale-data
```

## Performance Tuning

### For Low Capital ($5-$50)
```env
MIN_POSITION_USD=5.00
MAX_OPEN_POSITIONS=2
CONFIDENCE_THRESHOLD=0.70      # Higher confidence
```

### For Medium Capital ($50-$500)
```env
MIN_POSITION_USD=10.00
MAX_OPEN_POSITIONS=3
CONFIDENCE_THRESHOLD=0.65
```

### For Higher Capital ($500+)
```env
MIN_POSITION_USD=25.00
MAX_OPEN_POSITIONS=5
CONFIDENCE_THRESHOLD=0.60
TRADING_PAIRS=BTC/USDT,ETH/USDT,SOL/USDT,BNB/USDT,MATIC/USDT
```

## Security Best Practices

1. **Never commit `.env` file**
   - Already in `.gitignore`
   - Double-check before pushing

2. **Restrict API permissions**
   - Only enable "Spot Trading"
   - Disable "Withdraw" permission

3. **Use IP whitelist**
   - Add only your server IP in MEXC

4. **Rotate API keys regularly**
   - Change keys every 30-90 days

5. **Monitor unusual activity**
   - Check logs daily
   - Set up alerts

6. **Secure your server**
```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Enable firewall
sudo ufw allow 22/tcp    # SSH
sudo ufw allow 8080/tcp  # API
sudo ufw allow 3000/tcp  # Dashboard
sudo ufw enable

# Disable password auth (use SSH keys)
sudo nano /etc/ssh/sshd_config
# Set: PasswordAuthentication no
sudo systemctl restart sshd
```

## Development

### Project Structure
```
mangococo/
├── config/
│   ├── .env.example
│   ├── init-db.sql
│   └── prometheus.yml
├── services/
│   ├── market-data/      # Price streaming
│   ├── prediction/       # ML predictions
│   ├── signal/          # Trade signals
│   ├── risk/            # Risk management
│   ├── executor/        # Order execution
│   ├── position/        # Portfolio tracking
│   ├── api-gateway/     # REST API
│   └── dashboard/       # React UI
├── shared/              # Persistent data
├── docker-compose.yml
└── README.md
```

### Adding New Trading Pairs

1. Update `config/.env`:
```env
TRADING_PAIRS=BTC/USDT,ETH/USDT,NEW/USDT
```

2. Restart services:
```bash
docker compose restart market-data prediction signal
```

### Customizing ML Model

Edit `services/prediction/main.py`:
```python
# Adjust model architecture
model.add(LSTM(128, return_sequences=True))  # More layers
model.add(Dropout(0.3))                      # More dropout
```

Rebuild:
```bash
docker compose up -d --build prediction
```

## Support & Community

- **Issues**: [GitHub Issues](https://github.com/YOUR_USERNAME/mangococo/issues)
- **Documentation**: This README
- **Trading Discussion**: Use at your own risk!

## Disclaimer

**IMPORTANT**: This is educational software.

- Cryptocurrency trading carries significant risk
- You can lose your entire investment
- Past performance doesn't guarantee future results
- The bot makes autonomous decisions based on algorithms
- No trading strategy is risk-free
- Only invest what you can afford to lose

**By using this software, you acknowledge:**
- You understand the risks of automated trading
- You are solely responsible for your trading decisions
- The developers are not liable for any financial losses
- This is not financial advice

---
