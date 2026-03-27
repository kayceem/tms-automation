# ATRAD System Integration

This document explains how to use the ATRAD trading system alongside the existing TMS system.

## Overview

The project now supports **two trading management systems**:
1. **TMS** - Traditional TMS system (existing, fully implemented)
2. **ATRAD** - ATRAD system (newly integrated for order placement)

### Important Notes

- **Price fetching**: Always uses TMS system (for all users)
- **Order placement**: Supports both TMS and ATRAD
- **System selection**: Only applies to the **main order user**, NOT fetch users
- **Fetch users**: Always use TMS configuration

## System Detection

The system is automatically detected based on your user configuration file:

### Method 1: Explicit `system` Field (Recommended)

Add `"system": "atrad"` or `"system": "tms"` to your user config:

```json
{
  "user_id": "my_user",
  "system": "atrad",
  ...
}
```

### Method 2: Auto-Detection (Fallback)

If no `system` field is present, the system is detected based on configuration fields:
- ATRAD configs have: `username`, `password`, `atrad_base_url`
- TMS configs have: `xsrf_token`, `rid_cookie`, `access_token`

## ATRAD Configuration

### File Location

Place your ATRAD user config in the `users/` directory:
- Example: `users/atrad_user.json`
- Template: `users/atrad_user.example.json`

### Configuration Fields

```json
{
  "user_id": "atrad_user1",
  "atrad_base_url": "https://tms.stockhouse.com.np",
  "username": "MK221169",
  "password": "your_password_here",
  "account_id": "23463",

  "default_asset_select": "1",
  "default_board": "1",
  "default_order_type": "16",
  "default_product": "web",

  "ipo_sniper_duration_minutes": 2,
  "trigger_mode_poll_interval_ms": 100,
  "trigger_mode_refresh_interval_seconds": 60,
  "trigger_sell_poll_interval_ms": 500,
  "trigger_mode_slow_poll_interval_ms": 500,
  "trigger_mode_requests_per_fetch_user": 5
}
```

### Required Fields

| Field | Description | Example |
|-------|-------------|---------|
| `user_id` | Unique identifier for this user | `"atrad_user1"` |
| `atrad_base_url` | ATRAD system base URL | `"https://tms.stockhouse.com.np"` |
| `username` | ATRAD login username | `"MK221169"` |
| `password` | ATRAD login password | `"your_password"` |
| `account_id` | UCC/Account ID for orders | `"23463"` |

### Optional Fields

| Field | Default | Description |
|-------|---------|-------------|
| `default_asset_select` | `"1"` | 1=EQUITY, other for DEBT |
| `default_board` | `"1"` | 1=Regular, 4=Crossing, 7=CDS |
| `default_order_type` | `"16"` | 16=Day, 20=Market, etc. |
| `default_product` | `"web"` | Product identifier |

## Usage

### Command Line

The system is automatically detected from your user config file:

```bash
# Using ATRAD system (detected from config)
python main.py --user users/atrad_user.json --symbol NABIL --price 1000 --quantity 10

# Using TMS system (detected from config)
python main.py --user users/tms_user.json --symbol NABIL --price 1000 --quantity 10
```

### Programmatic Usage

```python
from utils.helpers import initialize_order_client_and_service

# Automatically detect and initialize the correct system
client, order_service, system_type = initialize_order_client_and_service('users/atrad_user.json')

print(f"Using system: {system_type}")  # 'atrad' or 'tms'

# Place order (API is the same for both systems)
response = order_service.execute_order(
    symbol='NABIL',
    order_price=1000.0,
    order_quantity=10,
    buy_or_sell=1  # 1=BUY, 2=SELL
)
```

### ATRAD-Specific API

If you need ATRAD-specific functionality:

```python
from api.atrad_client import ATRADClient
from config.atrad_user_config import ATRADUserConfig

# Load config
user_config = ATRADUserConfig.from_file('users/atrad_user.json')

# Create client
client = ATRADClient(user_config)

# Login (automatic, but can be called manually)
client.login()

# Place order
response = client.place_order(
    symbol='NABIL',
    quantity=10,
    price=1000.0,
    side='BUY',  # 'BUY' or 'SELL'
    board='1',  # Optional: override default board
    order_type='16'  # Optional: override default order type
)
```

## ATRAD vs TMS Differences

### Login/Authentication

| System | Authentication Method |
|--------|----------------------|
| TMS | Pre-obtained tokens (xsrf_token, rid_cookie, access_token) |
| ATRAD | Username/password login (automatic session management) |

### Order Placement

| System | Endpoint | Method |
|--------|----------|--------|
| TMS | `/tmsapi/orderApi/order/` | POST (JSON) |
| ATRAD | `/atsweb/order` | POST (Form data) |

### Request Format

**TMS:**
```json
{
  "securityId": 1234,
  "exchangeSecurityId": 5678,
  "orderPrice": 1000.0,
  "orderQuantity": 10,
  ...
}
```

**ATRAD:**
```
action=submitOrder
&txtSecurity=NABIL
&spnQuantity=10
&spnPrice=1000.00
&actionSelect=1
...
```

## Implementation Status

### Fully Implemented

- [x] ATRAD login and session management
- [x] Basic order placement (BUY/SELL)
- [x] Double buy support
- [x] System auto-detection
- [x] Configuration management
- [x] Session persistence
- [x] **IPO Snipe Mode** - Full ladder implementation (+2%, +4%, +6%, +8%, +10%)
- [x] **IPO Sniper Mode** - Duration-based aggressive placement at +10%
- [x] **IPO Trigger Mode** - LTP-based ladder triggering with skip_first, skip_second_last, no_ladder options
- [x] **Trigger Sell Mode** - Monitor LTP and sell when trigger price is reached

### 🎉 Feature Parity Achieved

ATRAD system now has **complete feature parity** with TMS system for all order placement modes!

### 📝 Future Enhancements

- [ ] Price fetching support (currently TMS-only by design)
- [ ] Additional ATRAD-specific features as needed
- [ ] Performance optimizations

## Multi-User Setup

### Main User (Order Placement)

Can use either TMS or ATRAD:

```bash
# ATRAD main user
python main.py --user users/atrad_main.json --symbol NABIL --price 1000 --quantity 10

# TMS main user
python main.py --user users/tms_main.json --symbol NABIL --price 1000 --quantity 10
```

### Fetch Users (Price Monitoring)

**Always use TMS configuration** for fetch users:

```bash
python main.py \
  --user users/atrad_main.json \
  --fetch-users users/tms_fetch1.json users/tms_fetch2.json \
  --ipo-trigger \
  --symbol NABIL \
  --price 1000 \
  --quantity 10
```

**Important:** Even if your main user is ATRAD, all fetch users must be TMS configs.

## Troubleshooting

### "Login failed" Error

- Check username/password in config
- Verify `atrad_base_url` is correct
- Ensure account is not locked

### "Session expired" Error

- ATRAD client automatically re-authenticates
- Check logs for login success/failure
- Verify password hasn't changed

### "Order placement failed" Error

- Check `account_id` matches your UCC
- Verify symbol/ticker is correct
- Check quantity meets minimum requirements
- Review ATRAD server response in logs

## Security Notes

⚠️ **Password Storage**: ATRAD configs store passwords in plain text. In production:
1. Use environment variables
2. Encrypt configuration files
3. Use a secrets management system
4. Rotate passwords regularly

## Examples

See `users/atrad_user.example.json` for a complete configuration template.

## Further Reading

- [Main README](../README.md)
- [User Configuration Guide](USER_CONFIG.md)
- [API Documentation](API.md)
