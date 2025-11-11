# Angel One SmartAPI WebSocket Integration

This document explains how to set up and use Angel One's SmartAPI WebSocket 2.0 for real-time Indian stock market data.

## Overview

Angel One SmartAPI provides real-time market data via WebSocket for NSE, BSE, MCX, and other Indian exchanges. Unlike Finnhub (which doesn't support Indian stocks on free tier), Angel One provides comprehensive coverage of Indian markets.

## Prerequisites

1. **Angel One Demat Account** - You need an active trading account with Angel One
2. **API Access** - Register for API access on Angel One SmartAPI portal
3. **Credentials** - Obtain the following:
   - Client Code (your trading account ID)
   - API Key
   - Auth Token (from login API)
   - Feed Token (from login API)

## Getting Your Credentials

### Step 1: Register for API Access
1. Visit [https://smartapi.angelone.in/](https://smartapi.angelone.in/)
2. Login with your Angel One credentials
3. Generate API credentials from the dashboard

### Step 2: Get Auth Token and Feed Token
You need to call the Angel One login API to get tokens:

```bash
curl -X POST https://apiconnect.angelone.in/rest/auth/angelbroking/user/v1/loginByPassword \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -H "X-UserType: USER" \
  -H "X-SourceID: WEB" \
  -H "X-ClientLocalIP: YOUR_LOCAL_IP" \
  -H "X-ClientPublicIP: YOUR_PUBLIC_IP" \
  -H "X-MACAddress: YOUR_MAC_ADDRESS" \
  -H "X-PrivateKey: YOUR_API_KEY" \
  -d '{
    "clientcode": "YOUR_CLIENT_CODE",
    "password": "YOUR_PASSWORD"
  }'
```

Response will contain:
```json
{
  "status": true,
  "message": "SUCCESS",
  "data": {
    "jwtToken": "YOUR_AUTH_TOKEN",
    "refreshToken": "...",
    "feedToken": "YOUR_FEED_TOKEN"
  }
}
```

### Step 3: Get Stock Tokens
Download the master scrip file to get token IDs for stocks:

```bash
# Download NSE symbols
curl -o nse_symbols.csv https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json
```

Or use the search API to find specific tokens.

## Environment Configuration

Update your `.env` file with Angel One credentials:

```properties
# Market Data Provider
MARKET_DATA_PROVIDER=angelone

# Angel One Credentials
ANGELONE_CLIENT_CODE=A12345
ANGELONE_API_KEY=your_api_key_here
ANGELONE_AUTH_TOKEN=eyJhbGciOiJIUzUxMiJ9...
ANGELONE_FEED_TOKEN=your_feed_token_here

# Token Mapping (Symbol -> Exchange Type + Token ID)
ANGELONE_TOKEN_MAP={
  "RELIANCE": {"exchangeType": 1, "token": "2885"},
  "TCS": {"exchangeType": 1, "token": "11536"},
  "INFY": {"exchangeType": 1, "token": "1594"},
  "HDFCBANK": {"exchangeType": 1, "token": "1333"},
  "ICICIBANK": {"exchangeType": 1, "token": "4963"},
  "WIPRO": {"exchangeType": 1, "token": "3787"},
  "LT": {"exchangeType": 1, "token": "11483"},
  "SBIN": {"exchangeType": 1, "token": "3045"},
  "BHARTIARTL": {"exchangeType": 1, "token": "10604"},
  "TATAMOTORS": {"exchangeType": 1, "token": "3456"}
}
```

### Exchange Types
- `1` = NSE Cash Market (nse_cm)
- `2` = NSE Futures & Options (nse_fo)
- `3` = BSE Cash Market (bse_cm)
- `4` = BSE Futures & Options (bse_fo)
- `5` = MCX Commodity (mcx_fo)
- `7` = NCX (ncx_fo)
- `13` = CDE (cde_fo)

## Finding Token IDs

### Option 1: Using Master Scrip File
```python
import json
import requests

# Download master scrip
response = requests.get('https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json')
data = response.json()

# Find token for a symbol
for item in data:
    if item['symbol'] == 'RELIANCE' and item['exch_seg'] == 'NSE':
        print(f"Token: {item['token']}, Exchange Type: 1")
```

### Option 2: Common NSE Stocks
Here are tokens for popular NSE stocks:

| Symbol | Token | Exchange Type | Name |
|--------|-------|---------------|------|
| RELIANCE | 2885 | 1 | Reliance Industries |
| TCS | 11536 | 1 | Tata Consultancy Services |
| INFY | 1594 | 1 | Infosys |
| HDFCBANK | 1333 | 1 | HDFC Bank |
| ICICIBANK | 4963 | 1 | ICICI Bank |
| HINDUNILVR | 1394 | 1 | Hindustan Unilever |
| ITC | 1660 | 1 | ITC Limited |
| KOTAKBANK | 1922 | 1 | Kotak Mahindra Bank |
| SBIN | 3045 | 1 | State Bank of India |
| BHARTIARTL | 10604 | 1 | Bharti Airtel |

## Testing the Integration

1. **Update environment variables** with your credentials
2. **Restart the portfolio server**:
   ```bash
   cd apps/portfolio-server
   PYTHONPATH=.:$PYTHONPATH python -m uvicorn main:app --reload
   ```

3. **Test with market quotes endpoint**:
   ```bash
   curl -H "Authorization: Bearer YOUR_JWT_TOKEN" \
     "http://localhost:8000/api/market/quotes?symbols=RELIANCE&symbols=TCS&symbols=INFY"
   ```

Expected response:
```json
{
  "data": [
    {
      "symbol": "RELIANCE",
      "price": "2456.75",
      "provider": "angelone",
      "source": "live-stream"
    },
    {
      "symbol": "TCS",
      "price": "3890.50",
      "provider": "angelone",
      "source": "live-stream"
    }
  ],
  "count": 2,
  "requested_at": "2025-11-08T00:00:00Z"
}
```

## Features

✅ **Real-time streaming** - Get live prices with sub-second latency  
✅ **Indian market support** - NSE, BSE, MCX, and more  
✅ **No subscription limits** on free tier (unlike Finnhub)  
✅ **Professional-grade** - Used by production trading systems  
✅ **Multiple subscription modes**:
  - LTP (Last Traded Price) - Minimal data, fastest updates
  - Quote - OHLC + Volume + Best bid/ask
  - Snap Quote - Full market depth with best 5 buy/sell orders

## Subscription Modes

The current implementation uses **LTP mode** (mode=1) for fastest updates. You can modify the mode in `AngelOneAdapter._batch_subscribe()`:

```python
"params": {
    "mode": 1,  # Change to 2 for Quote, 3 for SnapQuote
    "tokenList": token_list
}
```

## Limitations

- Maximum 3 concurrent WebSocket connections per client code
- Maximum 1000 token subscriptions per WebSocket session
- Auth token expires after 24 hours (need to re-login)
- Feed token expires after session ends

## Troubleshooting

### Connection Failed
- Check if API key and client code are correct
- Ensure auth token and feed token are valid (not expired)
- Verify network connectivity to Angel One servers

### No Price Updates
- Confirm token mapping is correct for your symbols
- Check if market is open (NSE: 9:15 AM - 3:30 PM IST)
- Verify subscription was successful (check logs)

### Authentication Errors
- Re-generate auth token and feed token using login API
- Ensure all required headers are present in WebSocket connection

## Additional Resources

- [Angel One SmartAPI Docs](https://smartapi.angelone.in/docs)
- [WebSocket Documentation](https://smartapi.angelone.in/docs/WebSocket)
- [Master Scrip Download](https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json)

## Support

For Angel One API issues, contact their support at:
- Email: support@angelbroking.com
- Developer Portal: https://smartapi.angelone.in/
