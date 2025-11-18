# Auth Server

Authentication and authorization microservice for the AgentInvest platform.

## Tech Stack

- **Runtime**: Node.js with TypeScript
- **Framework**: Express.js
- **ORM**: Prisma
- **Database**: PostgreSQL
- **Queue**: BullMQ (Redis)
- **Email**: SendGrid

## Setup

### Prerequisites

- Node.js 18+
- PostgreSQL 14+
- Redis (for queues)
- pnpm

### Installation

1. Install dependencies:
```bash
pnpm install --filter auth_server
```

2. Set up environment variables in `.env`:
```env
NODE_ENV=development
PORT=4000
DATABASE_URL=postgresql://user:password@localhost:5432/auth_db
JWT_SECRET_ACCESS=your-secret-access-key
JWT_SECRET_REFRESH=your-secret-refresh-key
JWT_SECRET_EMAIL=your-secret-email-key
INTERNAL_SERVICE_SECRET=your-internal-secret
CLIENT_URL=http://localhost:3000
AUTH_SERVER_URL=http://localhost:4000
SENDGRID_API_KEY=your-sendgrid-key
SENDER_EMAIL_ADDRESS=your-sender-email
REDIS_URL=redis://localhost:6379
```

3. Generate Prisma client:
```bash
pnpm --filter auth_server prisma:generate
```
Note: The Prisma schema is located in `shared/prisma/schema.prisma` and is shared across multiple servers.

4. Run database migrations:
```bash
pnpm --filter auth_server prisma:migrate
```

### Development

```bash
pnpm --filter auth_server dev
```

### Production Build

```bash
pnpm --filter auth_server build
pnpm --filter auth_server start
```

## API Endpoints

### Public Routes (`/api/auth`)

- `POST /organizations/register` - Register new organization and admin
- `POST /login` - User login
- `POST /refresh-token` - Refresh access token
- `POST /logout` - Logout user (protected)
- `POST /request-password-mail` - Request password reset email
- `POST /request-activation-mail` - Request activation email
- `POST /change-password` - Change password with token
- `POST /verify-email` - Verify email with token
- `POST /users` - Create new user (protected)
- `POST /user/update` - Update user profile (protected)

### Internal Routes (`/api/internal`)

- `POST /validate-token` - Validate JWT token (internal only)
- `GET /get-user-email/:userId` - Get user email by ID
- `GET /get-user-details/:userId` - Get user details by ID
- `GET /user-by-email/:email` - Get user by email

## Database Schema

### Organizations
- Multi-tenant organization support
- Subscription tiers and billing cycles
- Soft deletes

### Users
- Organization-scoped users
- Roles: admin, staff, viewer
- Two-factor authentication support
- Soft deletes

## Features

- JWT-based authentication
- Organization-based multi-tenancy
- Email verification
- Password reset
- Queue-based email sending
- Internal API for microservice communication
- Token validation endpoint for other services

## Middleware

Uses centralized middleware from `/middleware/js`:
- `authMiddleware` - Route protection
- `internalAuthMiddleware` - Internal service authentication
- `errorHandler` - Centralized error handling

