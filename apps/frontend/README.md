# Frontend Application

Next.js-based web application providing the user interface for the Agentic Trading Platform.

## 🏗️ Architecture Overview

The Frontend is a modern React application built with Next.js 14, providing:

- **Real-Time Dashboard**: Live portfolio monitoring and trading signals
- **User Management**: Authentication, profile, and subscription management
- **Trading Interface**: Manual and automated trading controls
- **Analytics Visualization**: Charts, graphs, and performance metrics
- **Admin Panel**: System configuration and user management

### Technology Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| **Framework** | Next.js 14 | React framework with SSR/SSG |
| **Language** | TypeScript | Type-safe development |
| **Styling** | Tailwind CSS | Utility-first CSS framework |
| **UI Components** | shadcn/ui | Accessible component library |
| **State Management** | React Hooks + Context | Client-side state |
| **Data Fetching** | SWR | Client-side data fetching |
| **Real-Time** | WebSocket + Redis | Live updates |
| **Charts** | Recharts | Data visualization |
| **Forms** | React Hook Form | Form validation |

## ⚙️ Setup

### Prerequisites
- Node.js 18+
- pnpm 9+

### Installation

```bash
# Install dependencies
pnpm install --filter frontend

# Generate environment files
cp apps/frontend/.env.example apps/frontend/.env.local
```

### Environment Variables

Create `.env.local` file in `apps/frontend/`:

```env
# API Endpoints
NEXT_PUBLIC_AUTH_SERVER_URL=http://localhost:4000
NEXT_PUBLIC_PORTFOLIO_SERVER_URL=http://localhost:8000
NEXT_PUBLIC_ALPHACOPILOT_SERVER_URL=http://localhost:8069

# Kafka (for browser-based monitoring)
NEXT_PUBLIC_KAFKA_BOOTSTRAP_SERVERS=localhost:9092

# Feature Flags
NEXT_PUBLIC_ENABLE_COPILOT=true
NEXT_PUBLIC_ENABLE_ADMIN=true
```

### Running Locally

```bash
# Development mode (with hot reload)
pnpm --filter frontend dev

# Production build
pnpm --filter frontend build
pnpm --filter frontend start

# Lint and type check
pnpm --filter frontend lint
pnpm --filter frontend check-types
```

## 🎯 Key Features

### 1. Real-Time Portfolio Dashboard

**Components:**
- Portfolio value chart (real-time updates)
- Asset allocation breakdown
- Active positions table
- P&L summary

**Update Frequency:**
- Prices: Real-time (<1s latency)
- Positions: On trade execution
- Analytics: 10-second polling

### 2. Trading Signal Visualization

**Signal Types:**
- NSE filing-based signals
- News sentiment signals
- Low-risk opportunities
- Algorithmic recommendations

### 3. Risk Alert System

**Alert Types:**
- Stop-loss triggers
- Take-profit triggers
- Position size warnings
- Market volatility alerts

### 4. AlphaCopilot Interface

**Features:**
- Natural language hypothesis input
- Backtest results visualization
- Alpha signal exploration
- Strategy comparison

## 📚 Related Documentation

- [Architecture Overview](../../docs/ARCHITECTURE.md)
- [Portfolio Server API](../portfolio-server/README.md)
- [Auth Server API](../auth_server/README.md)

---

**Built with ❤️ for modern trading interfaces**
