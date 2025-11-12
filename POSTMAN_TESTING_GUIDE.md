# 📮 Postman Testing Guide - Portfolio Server API

Complete testing guide for all implemented portfolio-server endpoints with sample payloads, expected logs, and database changes.

---

## 🔐 Prerequisites

### 1. Authentication Setup

All routes (except `/health` and `/api/pipeline/status`) require authentication via JWT token.

**Get Auth Token:**
```bash
# Login to auth server first (assuming auth_server is running on port 3000)
POST http://localhost:3000/api/auth/login
Content-Type: application/json

{
  "email": "test@example.com",
  "password": "your-password"
}

# Response will include a token - use it in all subsequent requests
```

**Postman Setup:**
1. Create environment variable `AUTH_TOKEN` with your JWT token
2. Add to all requests:
   - **Header:** `Authorization: Bearer {{AUTH_TOKEN}}`
   - OR **Cookie:** `token={{AUTH_TOKEN}}`

### 2. Base URL
```
http://localhost:8000
```
(Adjust port based on your portfolio-server configuration)

---

## 📊 API Endpoints by Feature

### **1. Health & Status**

#### GET `/health`
**Purpose:** Check if service is operational  
**Auth:** ❌ Not required

**Request:**
```bash
GET http://localhost:8000/health
```

**Expected Response:**
```json
{
  "status": "healthy",
  "timestamp": "2025-11-12T10:30:00Z",
  "service": "portfolio-server"
}
```

**Logs:**
```
INFO: Health check endpoint called
```

**DB Changes:** None

---

#### GET `/api/pipeline/status`
**Purpose:** Check Pathway pipeline status  
**Auth:** ❌ Not required

**Request:**
```bash
GET http://localhost:8000/api/pipeline/status
```

**Expected Response:**
```json
{
  "status": "running",
  "pipelines": {
    "allocation": "active",
    "regime_classification": "active",
    "market_data": "streaming"
  }
}
```

**Logs:**
```
INFO: Pipeline status requested
INFO: All pipelines operational
```

**DB Changes:** None

---

### **2. Portfolio Management**

#### GET `/portfolio/`
**Purpose:** Get or create portfolio for authenticated user  
**Auth:** ✅ Required

**Request:**
```bash
GET http://localhost:8000/portfolio/
Authorization: Bearer {{AUTH_TOKEN}}
```

**Expected Response (Existing Portfolio):**
```json
{
  "id": "clx123abc456",
  "organization_id": "org_001",
  "customer_id": "user_001",
  "portfolio_name": "John's Portfolio",
  "initial_investment": 100000.00,
  "investment_amount": 100000.00,
  "current_value": 105234.50,
  "investment_horizon_years": 3,
  "expected_return_target": 0.08,
  "risk_tolerance": "moderate",
  "liquidity_needs": "standard",
  "allocation_status": "allocated",
  "created_at": "2025-11-10T08:00:00Z",
  "updated_at": "2025-11-12T10:30:00Z"
}
```

**Expected Response (New Portfolio Created):**
```json
{
  "id": "clx789def012",
  "organization_id": "org_001",
  "customer_id": "user_002",
  "portfolio_name": "User's Portfolio",
  "initial_investment": 100000.00,
  "investment_amount": 100000.00,
  "current_value": 100000.00,
  "investment_horizon_years": 3,
  "expected_return_target": 0.08,
  "risk_tolerance": "moderate",
  "liquidity_needs": "standard",
  "allocation_status": "pending",
  "created_at": "2025-11-12T10:35:00Z",
  "updated_at": "2025-11-12T10:35:00Z"
}
```

**Logs:**
```
INFO: Fetching portfolio for user user_002 (org: org_001)
INFO: Portfolio not found, creating new portfolio
INFO: ✅ Portfolio created: clx789def012
INFO: ✅ Portfolio allocation task dispatched for clx789def012 (task_id=abc-123-def)
```

**DB Changes:**
- **INSERT** into `Portfolio` table:
  ```sql
  INSERT INTO Portfolio (
    id, organization_id, customer_id, portfolio_name,
    initial_investment, investment_amount, current_value,
    investment_horizon_years, expected_return_target,
    risk_tolerance, liquidity_needs, allocation_status, metadata
  ) VALUES (...)
  ```
- **Celery Task** dispatched: `allocate_new_portfolio_task`

---

#### GET `/portfolio/positions?page=1&limit=10`
**Purpose:** List all positions with pagination and filters  
**Auth:** ✅ Required

**Request:**
```bash
GET http://localhost:8000/portfolio/positions?page=1&limit=10&profitability=profitable&sortBy=pnl&sortOrder=desc
Authorization: Bearer {{AUTH_TOKEN}}
```

**Query Parameters:**
- `page`: Page number (default: 1)
- `limit`: Items per page (default: 10, max: 100)
- `search`: Search by symbol (optional)
- `profitability`: Filter by `profitable`, `loss-making`, or `breakeven` (optional)
- `sortBy`: Sort field - `symbol`, `quantity`, `currentValue`, `pnl`, `pnlPercentage`, `updatedAt`
- `sortOrder`: `asc` or `desc`

**Expected Response:**
```json
{
  "items": [
    {
      "id": "pos_001",
      "portfolio_id": "clx123abc456",
      "symbol": "RELIANCE",
      "exchange": "NSE",
      "segment": "EQ",
      "quantity": 50,
      "average_buy_price": 2450.00,
      "current_price": 2580.00,
      "current_value": 129000.00,
      "pnl": 6500.00,
      "pnl_percentage": 5.31,
      "position_type": "long",
      "status": "open",
      "updated_at": "2025-11-12T10:30:00Z"
    },
    {
      "id": "pos_002",
      "portfolio_id": "clx123abc456",
      "symbol": "TCS",
      "exchange": "NSE",
      "segment": "EQ",
      "quantity": 30,
      "average_buy_price": 3650.00,
      "current_price": 3720.00,
      "current_value": 111600.00,
      "pnl": 2100.00,
      "pnl_percentage": 1.92,
      "position_type": "long",
      "status": "open",
      "updated_at": "2025-11-12T09:15:00Z"
    }
  ],
  "page": 1,
  "limit": 10,
  "total": 15
}
```

**Logs:**
```
INFO: Listing positions for user user_001 (portfolio: clx123abc456)
INFO: Filters - profitability: profitable, sortBy: pnl desc
INFO: Found 15 positions, returning page 1 (10 items)
```

**DB Changes:** None (read-only)

---

#### GET `/portfolio/holding/{symbol}`
**Purpose:** Get specific holding details  
**Auth:** ✅ Required

**Request:**
```bash
GET http://localhost:8000/portfolio/holding/RELIANCE
Authorization: Bearer {{AUTH_TOKEN}}
```

**Expected Response:**
```json
{
  "portfolio_id": "clx123abc456",
  "position_id": "pos_001",
  "symbol": "RELIANCE",
  "exchange": "NSE",
  "segment": "EQ",
  "quantity": 50,
  "average_buy_price": 2450.00,
  "current_price": 2580.00,
  "current_value": 129000.00,
  "pnl": 6500.00,
  "pnl_percentage": 5.31,
  "position_type": "long",
  "status": "open",
  "metadata": {
    "sector": "Energy",
    "industry": "Oil & Gas"
  },
  "last_updated": "2025-11-12T10:30:00Z"
}
```

**Error Response (404):**
```json
{
  "detail": "Holding not found for symbol"
}
```

**Logs:**
```
INFO: Fetching holding for symbol RELIANCE (user: user_001)
INFO: Position found: pos_001
```

**DB Changes:** None (read-only)

---

#### GET `/portfolio/recent-trades?page=1&limit=10`
**Purpose:** List recent trades with filters  
**Auth:** ✅ Required

**Request:**
```bash
GET http://localhost:8000/portfolio/recent-trades?page=1&limit=10&side=BUY&status=executed
Authorization: Bearer {{AUTH_TOKEN}}
```

**Query Parameters:**
- `page`, `limit`: Pagination
- `symbol`: Filter by symbol (optional)
- `side`: Filter by `BUY` or `SELL` (optional)
- `orderType`: Filter by `market`, `limit`, `stop_loss`, etc. (optional)
- `status`: Filter by `executed`, `pending`, `rejected`, `cancelled` (optional)

**Expected Response:**
```json
{
  "items": [
    {
      "id": "trade_001",
      "portfolio_id": "clx123abc456",
      "symbol": "RELIANCE",
      "side": "BUY",
      "order_type": "market",
      "quantity": 50,
      "executed_quantity": 50,
      "executed_price": 2450.00,
      "status": "executed",
      "net_amount": 122500.00,
      "trade_type": "cash",
      "created_at": "2025-11-10T14:30:00Z",
      "execution_time": "2025-11-10T14:30:05Z"
    }
  ],
  "page": 1,
  "limit": 10,
  "total": 25
}
```

**Logs:**
```
INFO: Fetching recent trades for user user_001 (portfolio: clx123abc456)
INFO: Filters - side: BUY, status: executed
INFO: Found 25 trades, returning page 1
```

**DB Changes:** None (read-only)

---

### **3. Trading**

#### POST `/trades/`
**Purpose:** Submit a new trade order  
**Auth:** ✅ Required

**Request:**
```bash
POST http://localhost:8000/trades/
Authorization: Bearer {{AUTH_TOKEN}}
Content-Type: application/json

{
  "portfolio_id": "clx123abc456",
  "symbol": "INFY",
  "exchange": "NSE",
  "segment": "EQ",
  "side": "BUY",
  "order_type": "market",
  "quantity": 20,
  "trade_type": "cash",
  "source": "user",
  "metadata": {
    "note": "Adding IT sector exposure"
  }
}
```

**Payload Variants:**

**Limit Order:**
```json
{
  "portfolio_id": "clx123abc456",
  "symbol": "TCS",
  "side": "BUY",
  "order_type": "limit",
  "quantity": 10,
  "limit_price": 3600.00
}
```

**Stop Loss Order:**
```json
{
  "portfolio_id": "clx123abc456",
  "symbol": "RELIANCE",
  "side": "SELL",
  "order_type": "stop_loss",
  "quantity": 25,
  "trigger_price": 2400.00
}
```

**Expected Response:**
```json
{
  "success": true,
  "message": "Trade executed",
  "trades": [
    {
      "id": "trade_002",
      "symbol": "INFY",
      "side": "BUY",
      "order_type": "market",
      "status": "executed",
      "quantity": 20,
      "price": 1450.00,
      "executed_quantity": 20,
      "executed_price": 1450.00,
      "execution_time": "2025-11-12T10:45:00Z"
    }
  ],
  "pending_orders": 0,
  "portfolio": {
    "id": "clx123abc456",
    "current_value": 134000.50,
    "updated_at": "2025-11-12T10:45:00Z"
  }
}
```

**Error Response (400 - Validation):**
```json
{
  "detail": "limit orders require limit_price"
}
```

**Error Response (404 - Portfolio Not Found):**
```json
{
  "detail": "Portfolio not found"
}
```

**Error Response (403 - Access Denied):**
```json
{
  "detail": "Portfolio access denied"
}
```

**Logs:**
```
INFO: Processing trade request for portfolio clx123abc456
INFO: Symbol: INFY, Side: BUY, Quantity: 20, Order Type: market
INFO: Trade validated successfully
INFO: Executing market order for INFY
INFO: ✅ Trade executed: trade_002 (status=executed, qty=20, price=1450.00)
INFO: Portfolio value updated: 134000.50
```

**DB Changes:**
- **INSERT** into `Trade` table:
  ```sql
  INSERT INTO Trade (
    id, organization_id, portfolio_id, customer_id,
    symbol, exchange, segment, side, order_type,
    quantity, executed_quantity, executed_price,
    status, net_amount, trade_type, source, metadata
  ) VALUES (...)
  ```
- **INSERT/UPDATE** `Position` table (if position exists, update; else create):
  ```sql
  -- If buying INFY for first time
  INSERT INTO Position (
    portfolio_id, symbol, exchange, segment,
    quantity, average_buy_price, current_price,
    current_value, pnl, position_type, status
  ) VALUES (...)
  
  -- If adding to existing position
  UPDATE Position SET
    quantity = quantity + 20,
    average_buy_price = (weighted average),
    current_value = ...,
    pnl = ...
  WHERE portfolio_id = ... AND symbol = 'INFY'
  ```
- **UPDATE** `Portfolio` table:
  ```sql
  UPDATE Portfolio SET
    current_value = ...,
    updated_at = NOW()
  WHERE id = 'clx123abc456'
  ```

---

### **4. Market Data**

#### GET `/market/quotes?symbols=RELIANCE,TCS,INFY`
**Purpose:** Get live market quotes for symbols  
**Auth:** ✅ Required

**Request:**
```bash
GET http://localhost:8000/market/quotes?symbols=RELIANCE&symbols=TCS&symbols=INFY
Authorization: Bearer {{AUTH_TOKEN}}
```

**Expected Response:**
```json
{
  "data": [
    {
      "symbol": "RELIANCE",
      "price": 2580.00,
      "provider": "angelone",
      "source": "live-stream"
    },
    {
      "symbol": "TCS",
      "price": 3720.00,
      "provider": "angelone",
      "source": "cache"
    },
    {
      "symbol": "INFY",
      "price": 1450.00,
      "provider": "angelone",
      "source": "live-stream"
    }
  ],
  "count": 3,
  "requested_at": "2025-11-12T10:50:00Z",
  "missing": null
}
```

**With Historical Candles:**
```bash
GET http://localhost:8000/market/quotes?symbols=RELIANCE&candle=1d
```

**Response with Candles:**
```json
{
  "data": [...],
  "count": 1,
  "requested_at": "2025-11-12T10:50:00Z",
  "metadata": {
    "candles": {
      "RELIANCE": [
        {
          "timestamp": "2025-11-11T09:15:00Z",
          "open": 2550.00,
          "high": 2595.00,
          "low": 2540.00,
          "close": 2580.00,
          "volume": 1234567
        }
      ]
    }
  }
}
```

**Logs:**
```
INFO: Market quote request for 3 symbols
INFO: Fetching prices for RELIANCE, TCS, INFY
INFO: RELIANCE - cache hit, price: 2580.00
INFO: TCS - live stream, price: 3720.00
INFO: INFY - live stream, price: 1450.00
```

**DB Changes:** None (data streamed from WebSocket/cache)

---

#### GET `/market/subscribed-symbols`
**Purpose:** Get list of all WebSocket-subscribed symbols  
**Auth:** ✅ Required

**Request:**
```bash
GET http://localhost:8000/market/subscribed-symbols
Authorization: Bearer {{AUTH_TOKEN}}
```

**Expected Response:**
```json
{
  "subscribed": [
    "RELIANCE", "TCS", "INFY", "HDFC", "ICICI", "..."
  ],
  "count": 500,
  "provider": "angelone"
}
```

**Logs:**
```
INFO: Subscribed symbols requested
INFO: Returning 500 symbols from Angel One adapter
```

**DB Changes:** None

---

### **5. Investment Objectives**

#### POST `/objectives/`
**Purpose:** Create investment objective and trigger portfolio allocation  
**Auth:** ✅ Required

**Request:**
```bash
POST http://localhost:8000/objectives/
Authorization: Bearer {{AUTH_TOKEN}}
Content-Type: application/json

{
  "name": "Retirement Fund - Conservative",
  "investable_amount": 500000.00,
  "investment_horizon_years": 10,
  "expected_return_target": 0.12,
  "risk_tolerance": "low",
  "liquidity_needs": "standard",
  "rebalancing_frequency": "quarterly",
  "constraints": {
    "sector_limits": {
      "IT": 30,
      "Banking": 25
    },
    "esg_exclusions": ["tobacco", "alcohol"]
  },
  "preferences": {
    "dividend_preference": "high",
    "tax_efficiency": "priority"
  }
}
```

**Expected Response:**
```json
{
  "objective": {
    "id": "obj_001",
    "user_id": "user_001",
    "name": "Retirement Fund - Conservative",
    "investable_amount": 500000.00,
    "investment_horizon_years": 10,
    "investment_horizon_label": "long",
    "target_return": 12.00,
    "risk_tolerance": "low",
    "risk_aversion_lambda": 5.0,
    "liquidity_needs": "standard",
    "rebalancing_frequency": "quarterly",
    "constraints": {
      "sector_limits": {"IT": 30, "Banking": 25},
      "esg_exclusions": ["tobacco", "alcohol"]
    },
    "preferences": {
      "dividend_preference": "high",
      "tax_efficiency": "priority"
    },
    "missing_fields": [],
    "completion_status": "complete",
    "status": "active",
    "source": "api:create",
    "created_at": "2025-11-12T11:00:00Z",
    "updated_at": "2025-11-12T11:00:00Z"
  },
  "portfolio_id": "clx123abc456",
  "allocation": {
    "weights": {
      "RELIANCE": 0.15,
      "TCS": 0.20,
      "HDFC": 0.18,
      "INFY": 0.12,
      "ITC": 0.10,
      "CASH": 0.25
    },
    "expected_return": 0.115,
    "expected_risk": 0.08,
    "objective_value": 0.0952,
    "message": "Allocation optimized for risk=low, regime=sideways",
    "regime": "sideways",
    "progress_ratio": 1.0
  },
  "last_rebalanced_at": "2025-11-12T11:00:15Z",
  "next_rebalance_at": "2026-02-12T11:00:15Z"
}
```

**Logs:**
```
INFO: Creating objective for user user_001 (portfolio clx123abc456, regime=sideways)
INFO: Objective persisted: obj_001
INFO: Applying objective to portfolio clx123abc456
INFO: Portfolio updated with objective preferences
INFO: Triggering allocation pipeline...
INFO: ⚙️  Allocation pipeline executing for portfolio clx123abc456
INFO: Regime: sideways, Risk: low, Horizon: 10 years
INFO: Allocation complete - weights: RELIANCE=15%, TCS=20%, HDFC=18%...
INFO: ✅ Allocation result persisted
INFO: Next rebalance scheduled for: 2026-02-12
```

**DB Changes:**
- **INSERT** into `Objective` table
- **UPDATE** `Portfolio` table with objective references
- **INSERT** into `PortfolioAllocation` table
- **INSERT** into `RebalanceRun` table (audit trail)

---

#### POST `/objectives/intake`
**Purpose:** Interactive objective intake from transcript or partial JSON  
**Auth:** ✅ Required

**Request (First Call - Transcript):**
```bash
POST http://localhost:8000/objectives/intake
Authorization: Bearer {{AUTH_TOKEN}}
Content-Type: application/json

{
  "name": "My Investment Goal",
  "transcript": "User: I have 15 lakhs to invest.\nUser: I want to invest for my child's education in 5 years.\nUser: I'm okay with moderate risk.\nUser: I need some liquidity for emergencies.",
  "source": "chatbot"
}
```

**Expected Response (Pending - Missing Fields):**
```json
{
  "objective_id": "obj_002",
  "status": "pending",
  "missing_fields": ["target_return"],
  "structured_payload": {
    "investable_amount": 1500000.00,
    "investment_horizon": "medium",
    "investment_horizon_years": 5,
    "risk_tolerance": "moderate",
    "liquidity_needs": "high"
  },
  "warnings": [],
  "message": "Please provide: target_return",
  "created": true,
  "completion_timestamp": null,
  "allocation": null
}
```

**Request (Second Call - Completing Data):**
```bash
POST http://localhost:8000/objectives/intake
Authorization: Bearer {{AUTH_TOKEN}}
Content-Type: application/json

{
  "objective_id": "obj_002",
  "structured_payload": {
    "target_return": 14.0
  }
}
```

**Expected Response (Complete):**
```json
{
  "objective_id": "obj_002",
  "status": "complete",
  "missing_fields": [],
  "structured_payload": {
    "investable_amount": 1500000.00,
    "investment_horizon": "medium",
    "investment_horizon_years": 5,
    "risk_tolerance": "moderate",
    "liquidity_needs": "high",
    "target_return": 14.0
  },
  "warnings": [],
  "message": "Objective complete, portfolio allocated successfully",
  "created": false,
  "completion_timestamp": "2025-11-12T11:05:00Z",
  "allocation": {
    "weights": {...},
    "expected_return": 0.135,
    "expected_risk": 0.12
  }
}
```

**Logs:**
```
INFO: Intake request received (objective_id=None, has_transcript=True)
INFO: Extracting parameters from transcript...
INFO: Extracted: amount=1500000, horizon=medium, risk=moderate, liquidity=high
INFO: Missing fields: target_return
INFO: Creating pending objective: obj_002
INFO: Status: pending, awaiting additional data

# Second request
INFO: Intake request received (objective_id=obj_002)
INFO: Merging structured payload with existing data
INFO: All mandatory fields present, finalizing objective
INFO: Triggering portfolio allocation...
INFO: ✅ Objective intake complete
```

**DB Changes:**
- **First Call:** INSERT `Objective` with `completion_status='pending'`
- **Second Call:** UPDATE `Objective` to `completion_status='complete'`, INSERT `PortfolioAllocation`

---

### **6. Market Regime Classification**

#### GET `/regime/current`
**Purpose:** Get current market regime classification  
**Auth:** ✅ Required

**Request:**
```bash
GET http://localhost:8000/regime/current
Authorization: Bearer {{AUTH_TOKEN}}
```

**Expected Response:**
```json
{
  "regime": "Bull Market",
  "regime_id": 0,
  "timestamp": "2025-11-12T11:10:00Z",
  "confidence": 0.85,
  "indicators": {
    "sma_50": 23450.00,
    "sma_200": 22800.00,
    "volatility": 0.012,
    "rsi": 62.5,
    "macd": 125.3
  }
}
```

**Logs:**
```
INFO: Current regime requested
INFO: Fetching latest regime from stream
INFO: Regime: Bull Market (state_id=0), confidence=0.85
```

**DB Changes:** None (read from Pathway stream)

---

#### GET `/regime/history?limit=100`
**Purpose:** Get historical regime classifications  
**Auth:** ✅ Required

**Request:**
```bash
GET http://localhost:8000/regime/history?limit=50
Authorization: Bearer {{AUTH_TOKEN}}
```

**Expected Response:**
```json
{
  "history": [
    {
      "timestamp": "2025-11-12T11:10:00Z",
      "regime": "Bull Market",
      "regime_id": 0
    },
    {
      "timestamp": "2025-11-12T11:09:00Z",
      "regime": "Bull Market",
      "regime_id": 0
    },
    {
      "timestamp": "2025-11-12T11:08:00Z",
      "regime": "Sideways Market",
      "regime_id": 3
    }
  ],
  "count": 50,
  "requested_limit": 50
}
```

**Logs:**
```
INFO: Regime history requested (limit=50)
INFO: Fetching historical regime data from stream
INFO: Returning 50 regime data points
```

**DB Changes:** None

---

#### GET `/regime/statistics`
**Purpose:** Get statistical analysis of regimes  
**Auth:** ✅ Required

**Request:**
```bash
GET http://localhost:8000/regime/statistics
Authorization: Bearer {{AUTH_TOKEN}}
```

**Expected Response:**
```json
{
  "statistics": {
    "Bull Market": {
      "percentage": 35.2,
      "avg_return": 0.18,
      "avg_volatility": 0.015,
      "observations": 1250
    },
    "Bear Market": {
      "percentage": 15.8,
      "avg_return": -0.12,
      "avg_volatility": 0.025,
      "observations": 560
    },
    "Sideways Market": {
      "percentage": 42.0,
      "avg_return": 0.05,
      "avg_volatility": 0.010,
      "observations": 1490
    },
    "High Volatility": {
      "percentage": 7.0,
      "avg_return": -0.08,
      "avg_volatility": 0.035,
      "observations": 248
    }
  }
}
```

**Logs:**
```
INFO: Regime statistics requested
INFO: Calculating statistics across all regimes
INFO: Regime distribution - Bull: 35.2%, Bear: 15.8%, Sideways: 42.0%, High Vol: 7.0%
```

**DB Changes:** None

---

#### POST `/regime/train`
**Purpose:** Retrain regime classification model  
**Auth:** ✅ Required (Admin recommended)

**Request:**
```bash
POST http://localhost:8000/regime/train
Authorization: Bearer {{AUTH_TOKEN}}
Content-Type: application/json

{
  "start_date": "2020-01-01",
  "end_date": "2025-11-12",
  "n_regimes": 4
}
```

**Expected Response:**
```json
{
  "success": true,
  "message": "Model retrained successfully",
  "n_regimes": 4,
  "regime_mapping": {
    "0": "Bull Market",
    "1": "Bear Market",
    "2": "High Volatility",
    "3": "Sideways Market"
  },
  "training_samples": 1450,
  "model_path": "/path/to/regime_model_20251112.pkl"
}
```

**Logs:**
```
INFO: Regime model retraining requested
INFO: Training period: 2020-01-01 to 2025-11-12, n_regimes=4
INFO: Fetching historical market data...
INFO: Calculating technical indicators...
INFO: Training HMM model...
INFO: ✅ Model trained successfully (1450 samples)
INFO: Regime mapping: {0: Bull, 1: Bear, 2: High Vol, 3: Sideways}
INFO: Model saved to: regime_model_20251112.pkl
WARNING: Service restart required for new model to take effect
```

**DB Changes:**
- Model file saved to disk
- No DB changes (requires restart to apply)

---

#### POST `/regime/sensitivity`
**Purpose:** Update regime transition sensitivity  
**Auth:** ✅ Required (Admin recommended)

**Request:**
```bash
POST http://localhost:8000/regime/sensitivity
Authorization: Bearer {{AUTH_TOKEN}}
Content-Type: application/json

{
  "alpha_diag": 10.0
}
```

**Expected Response:**
```json
{
  "success": true,
  "message": "Sensitivity updated successfully",
  "alpha_diag": 10.0,
  "note": "Service restart required to apply changes"
}
```

**Logs:**
```
INFO: Regime sensitivity update requested
INFO: Current alpha_diag: 5.0, new alpha_diag: 10.0
INFO: ✅ Sensitivity configuration updated
WARNING: Service restart required for changes to take effect
```

**DB Changes:**
- Configuration file updated
- No runtime changes until restart

---

## 🔍 Testing Sequences

### **Sequence 1: New User Onboarding**

```
1. GET /portfolio/
   → Creates portfolio if not exists
   → Triggers allocation task

2. POST /objectives/intake (with transcript)
   → Extracts investment parameters
   → Returns missing fields

3. POST /objectives/intake (completing data)
   → Finalizes objective
   → Triggers portfolio allocation
   → Returns allocation weights

4. GET /portfolio/positions
   → Shows allocated positions
```

### **Sequence 2: Trading Flow**

```
1. GET /market/quotes?symbols=RELIANCE,TCS
   → Get current prices

2. POST /trades/ (BUY market order)
   → Execute trade
   → Updates portfolio & positions

3. GET /portfolio/positions
   → Verify new position appears

4. GET /portfolio/recent-trades
   → Verify trade in history

5. POST /trades/ (SELL limit order)
   → Place limit order
   → Status: pending

6. GET /portfolio/recent-trades?status=pending
   → See pending orders
```

### **Sequence 3: Regime-Based Strategy**

```
1. GET /regime/current
   → Check current regime

2. GET /regime/statistics
   → Analyze regime performance

3. POST /objectives/ (with regime-aware constraints)
   → Create objective considering current regime
   → Allocation adapts to regime

4. GET /regime/history?limit=100
   → Monitor regime transitions over time
```

---

## 🐛 Error Testing

### **401 - Unauthorized**
```bash
# Request without token
GET http://localhost:8000/portfolio/

# Response
{
  "detail": "Not authorized, no token"
}
```

### **403 - Forbidden**
```bash
# User trying to access another user's portfolio
GET http://localhost:8000/portfolio/holding/RELIANCE
Authorization: Bearer <different_user_token>

# Response
{
  "detail": "Not authorized to access this user"
}
```

### **400 - Validation Error**
```bash
POST http://localhost:8000/trades/
{
  "portfolio_id": "clx123abc456",
  "symbol": "INFY",
  "side": "BUY",
  "order_type": "limit"
  # Missing limit_price
}

# Response
{
  "detail": "limit orders require limit_price"
}
```

### **404 - Not Found**
```bash
GET http://localhost:8000/portfolio/holding/INVALIDSTOCK

# Response
{
  "detail": "Holding not found for symbol"
}
```

---

## 📝 Postman Collection JSON

Save this as `portfolio-server.postman_collection.json`:

```json
{
  "info": {
    "name": "Portfolio Server API",
    "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
  },
  "item": [
    {
      "name": "Health",
      "request": {
        "method": "GET",
        "header": [],
        "url": {
          "raw": "{{BASE_URL}}/health",
          "host": ["{{BASE_URL}}"],
          "path": ["health"]
        }
      }
    },
    {
      "name": "Get Portfolio",
      "request": {
        "method": "GET",
        "header": [
          {
            "key": "Authorization",
            "value": "Bearer {{AUTH_TOKEN}}",
            "type": "text"
          }
        ],
        "url": {
          "raw": "{{BASE_URL}}/portfolio/",
          "host": ["{{BASE_URL}}"],
          "path": ["portfolio", ""]
        }
      }
    },
    {
      "name": "List Positions",
      "request": {
        "method": "GET",
        "header": [
          {
            "key": "Authorization",
            "value": "Bearer {{AUTH_TOKEN}}",
            "type": "text"
          }
        ],
        "url": {
          "raw": "{{BASE_URL}}/portfolio/positions?page=1&limit=10",
          "host": ["{{BASE_URL}}"],
          "path": ["portfolio", "positions"],
          "query": [
            {"key": "page", "value": "1"},
            {"key": "limit", "value": "10"}
          ]
        }
      }
    },
    {
      "name": "Submit Trade - Market Buy",
      "request": {
        "method": "POST",
        "header": [
          {
            "key": "Authorization",
            "value": "Bearer {{AUTH_TOKEN}}",
            "type": "text"
          },
          {
            "key": "Content-Type",
            "value": "application/json",
            "type": "text"
          }
        ],
        "body": {
          "mode": "raw",
          "raw": "{\n  \"portfolio_id\": \"{{PORTFOLIO_ID}}\",\n  \"symbol\": \"RELIANCE\",\n  \"side\": \"BUY\",\n  \"order_type\": \"market\",\n  \"quantity\": 10\n}"
        },
        "url": {
          "raw": "{{BASE_URL}}/trades/",
          "host": ["{{BASE_URL}}"],
          "path": ["trades", ""]
        }
      }
    },
    {
      "name": "Get Market Quotes",
      "request": {
        "method": "GET",
        "header": [
          {
            "key": "Authorization",
            "value": "Bearer {{AUTH_TOKEN}}",
            "type": "text"
          }
        ],
        "url": {
          "raw": "{{BASE_URL}}/market/quotes?symbols=RELIANCE&symbols=TCS",
          "host": ["{{BASE_URL}}"],
          "path": ["market", "quotes"],
          "query": [
            {"key": "symbols", "value": "RELIANCE"},
            {"key": "symbols", "value": "TCS"}
          ]
        }
      }
    },
    {
      "name": "Create Objective",
      "request": {
        "method": "POST",
        "header": [
          {
            "key": "Authorization",
            "value": "Bearer {{AUTH_TOKEN}}",
            "type": "text"
          },
          {
            "key": "Content-Type",
            "value": "application/json",
            "type": "text"
          }
        ],
        "body": {
          "mode": "raw",
          "raw": "{\n  \"name\": \"Growth Portfolio\",\n  \"investable_amount\": 100000,\n  \"investment_horizon_years\": 5,\n  \"expected_return_target\": 0.15,\n  \"risk_tolerance\": \"high\",\n  \"liquidity_needs\": \"low\"\n}"
        },
        "url": {
          "raw": "{{BASE_URL}}/objectives/",
          "host": ["{{BASE_URL}}"],
          "path": ["objectives", ""]
        }
      }
    },
    {
      "name": "Objective Intake - Transcript",
      "request": {
        "method": "POST",
        "header": [
          {
            "key": "Authorization",
            "value": "Bearer {{AUTH_TOKEN}}",
            "type": "text"
          },
          {
            "key": "Content-Type",
            "value": "application/json",
            "type": "text"
          }
        ],
        "body": {
          "mode": "raw",
          "raw": "{\n  \"transcript\": \"User: I have 10 lakhs to invest.\\nUser: Looking at 3 year horizon.\\nUser: Moderate risk is fine.\",\n  \"source\": \"chatbot\"\n}"
        },
        "url": {
          "raw": "{{BASE_URL}}/objectives/intake",
          "host": ["{{BASE_URL}}"],
          "path": ["objectives", "intake"]
        }
      }
    },
    {
      "name": "Current Regime",
      "request": {
        "method": "GET",
        "header": [
          {
            "key": "Authorization",
            "value": "Bearer {{AUTH_TOKEN}}",
            "type": "text"
          }
        ],
        "url": {
          "raw": "{{BASE_URL}}/regime/current",
          "host": ["{{BASE_URL}}"],
          "path": ["regime", "current"]
        }
      }
    },
    {
      "name": "Regime History",
      "request": {
        "method": "GET",
        "header": [
          {
            "key": "Authorization",
            "value": "Bearer {{AUTH_TOKEN}}",
            "type": "text"
          }
        ],
        "url": {
          "raw": "{{BASE_URL}}/regime/history?limit=100",
          "host": ["{{BASE_URL}}"],
          "path": ["regime", "history"],
          "query": [{"key": "limit", "value": "100"}]
        }
      }
    }
  ],
  "variable": [
    {
      "key": "BASE_URL",
      "value": "http://localhost:8000",
      "type": "string"
    },
    {
      "key": "AUTH_TOKEN",
      "value": "your_jwt_token_here",
      "type": "string"
    },
    {
      "key": "PORTFOLIO_ID",
      "value": "your_portfolio_id",
      "type": "string"
    }
  ]
}
```

---

## 📊 Database Inspection Queries

After making requests, inspect database changes:

```sql
-- Check portfolio creation
SELECT id, customer_id, portfolio_name, current_value, allocation_status 
FROM Portfolio 
ORDER BY created_at DESC LIMIT 5;

-- Check objectives
SELECT id, user_id, name, completion_status, status, investable_amount, risk_tolerance
FROM Objective
ORDER BY created_at DESC LIMIT 5;

-- Check trades
SELECT id, portfolio_id, symbol, side, order_type, quantity, status, executed_price
FROM Trade
ORDER BY created_at DESC LIMIT 10;

-- Check positions
SELECT id, portfolio_id, symbol, quantity, average_buy_price, current_value, pnl, pnl_percentage
FROM Position
WHERE portfolio_id = 'your_portfolio_id';

-- Check allocations
SELECT id, portfolio_id, allocation_weights, expected_return, expected_risk, regime
FROM PortfolioAllocation
ORDER BY created_at DESC LIMIT 5;

-- Check rebalance runs
SELECT id, portfolio_id, trigger_reason, regime, status, result
FROM RebalanceRun
ORDER BY created_at DESC LIMIT 5;
```

---

## 🎯 Quick Start Checklist

- [ ] Auth server running and accessible
- [ ] Portfolio server running on port 8000
- [ ] Database migrations applied
- [ ] Celery workers running for async tasks
- [ ] Kafka/Pathway pipelines active
- [ ] Angel One WebSocket connected (check logs for "✅ Nifty-500 pre-fetch complete")
- [ ] Postman collection imported
- [ ] Environment variables set (BASE_URL, AUTH_TOKEN)
- [ ] Test user created in auth server

Happy Testing! 🚀
