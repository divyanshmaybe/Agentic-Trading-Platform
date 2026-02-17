# Auth Server

Authentication and authorization microservice providing secure user management and session handling.

## 🏗️ Architecture Overview

The Auth Server is a Node.js/TypeScript service responsible for:

- **User Authentication**: Registration, login, password management
- **Session Management**: JWT-based access and refresh tokens
- **Email Workflows**: Verification, password reset, notifications via SendGrid
- **Multi-tenancy**: Organization-scoped user management
- **API Security**: Internal service authentication and rate limiting

### Technology Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| **Runtime** | Node.js 18+ | JavaScript runtime environment |
| **Framework** | Express.js | Web application framework |
| **Language** | TypeScript | Type-safe development |
| **ORM** | Prisma | Type-safe database access |
| **Database** | PostgreSQL 16 | Relational database |
| **Queue** | BullMQ + Redis | Job queue for email sending |
| **Email** | SendGrid | Transactional email delivery |
| **Monitoring** | Prometheus | Metrics and observability |

### Data Flow

```
Client Request          Auth Server              External Services
─────────────          ───────────              ─────────────────

Registration ────▶ ┌──────────────┐
   Request         │   Express    │
                   │   Routes     │──────────▶ PostgreSQL
Login ────────▶    └──────────────┘             (User DB)
   Request                │
                          ▼
Password Reset ────▶ ┌──────────────┐
   Request           │  BullMQ Job  │──────────▶ SendGrid
                     │    Queue     │              (Email)
                     └──────────────┘
                          │
                          ▼
Internal API ─────▶  ┌──────────────┐
Token Validation     │   Internal   │──────────▶ Redis
                     │   Services   │            (Cache)
                     └──────────────┘
```

## 🎯 Key Features

### 1. User Authentication

**Registration Flow:**
- Email validation and uniqueness check
- Password hashing with bcrypt
- Organization association
- Email verification token generation
- Welcome email via job queue

**Login Flow:**
- Credentials validation
- JWT token generation (access + refresh)
- Session creation
- Rate limiting protection

**Password Management:**
- Secure password reset via email
- Token-based verification
- Password strength requirements

### 2. JWT Token Management

**Token Types:**
- **Access Token**: Short-lived (15 minutes), used for API requests
- **Refresh Token**: Long-lived (7 days), used to obtain new access tokens
- **Email Token**: One-time use for email verification/password reset

**Security:**
- Separate secret keys for each token type
- Automatic expiration
- Token refresh mechanism
- Blacklist support for revoked tokens

### 3. Email Workflows

**BullMQ Job Queue:**
- Async email processing
- Retry logic with exponential backoff
- Job prioritization
- Dead letter queue for failed jobs

**Email Templates:**
- Welcome email
- Email verification
- Password reset
- OTP verification

### 4. Multi-Tenancy Support

**Organization Management:**
- Organization creation during registration
- User-organization association
- Organization-scoped data access
- Subscription tier management

### 5. Internal Service API

**Service-to-Service Communication:**
- Token validation endpoint
- User details retrieval
- Email lookup
- Internal service authentication

## ⚙️ Setup

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

---

## 🔄 Important Flows

### User Registration Flow

```
1. Client Submission
   └─▶ POST /api/auth/organizations/register
   └─▶ Email, password, organization name

2. Validation
   └─▶ Email format check → Uniqueness validation → Password strength

3. Organization Creation
   └─▶ New organization record → Admin role assignment

4. User Creation
   └─▶ Password hashing → User record → Organization association

5. Email Verification
   └─▶ Token generation → BullMQ job → SendGrid email → Verification link

6. Response
   └─▶ Access token → Refresh token → User profile
```

### Login Flow

```
1. Credentials Submission
   └─▶ POST /api/auth/login
   └─▶ Email + password

2. User Lookup
   └─▶ Find by email → Organization check → Status validation

3. Password Verification
   └─▶ Bcrypt comparison → Rate limit check

4. Token Generation
   └─▶ JWT signing (access + refresh) → Redis session storage

5. Response
   └─▶ Tokens → User profile → Organization details
```

### Password Reset Flow

```
1. Reset Request
   └─▶ POST /api/auth/request-password-mail
   └─▶ Email address

2. Token Generation
   └─▶ Reset token creation → Database storage → Expiry (1 hour)

3. Email Dispatch
   └─▶ BullMQ job → SendGrid → Reset link email

4. Token Verification
   └─▶ POST /api/auth/change-password
   └─▶ Token validation → Expiry check

5. Password Update
   └─▶ New password hashing → Database update → Token invalidation
```

### Internal Service Authentication

```
1. Service Request
   └─▶ POST /api/internal/validate-token
   └─▶ JWT token in header

2. Token Validation
   └─▶ Signature verification → Expiry check → User lookup

3. Response
   └─▶ User ID → Organization ID → Role → Permissions
```

---

## 📊 Monitoring & Metrics

The service exposes Prometheus metrics at `/metrics`:

**Key Metrics:**
- `http_requests_total` - Total HTTP requests by endpoint and status
- `http_request_duration_seconds` - Request latency histogram
- `auth_login_attempts_total` - Login attempts (success/failure)
- `auth_registration_total` - New user registrations
- `email_jobs_total` - Email jobs by status
- `nodejs_heap_size_used_bytes` - Memory usage
- `nodejs_eventloop_lag_seconds` - Event loop lag

**Health Checks:**
- `GET /health` - Service health status
- Database connection check
- Redis connection check

**Grafana Dashboard:**
Access at http://localhost:3001 (Auth Server Dashboard)

---

## 🧪 Testing

```bash
# Run all tests
pnpm test

# Run with coverage
pnpm test:cov

# Run specific test file
pnpm test tests/auth.test.ts

# Integration tests
pnpm test:integration
```

---

## 🔐 Security Considerations

1. **Password Security**
   - Bcrypt hashing with salt rounds: 10
   - Minimum password length: 8 characters
   - Password complexity requirements

2. **Token Security**
   - Separate secret keys for each token type
   - Short-lived access tokens (15 minutes)
   - Secure refresh token rotation
   - HTTPS-only cookie transmission

3. **Rate Limiting**
   - Login attempts: 5 per 15 minutes per IP
   - API requests: 500 per 15 minutes per IP
   - Password reset: 3 per hour per email

4. **CORS Configuration**
   - Whitelist specific origins
   - Credentials allowed for authenticated requests
   - Preflight caching

5. **Session Management**
   - Redis-backed sessions
   - Automatic expiration
   - Logout token blacklisting

---

## 🐛 Troubleshooting

### Email Not Sending
```bash
# Check BullMQ queue
redis-cli -p 6379 llen bull:email:wait

# View worker logs
docker logs auth_email_worker -f

# Verify SendGrid configuration
curl -X POST https://api.sendgrid.com/v3/mail/send \
  -H "Authorization: Bearer $SENDGRID_API_KEY"
```

### Database Connection Issues
```bash
# Test database connection
psql -h localhost -p 5432 -U auth_user -d auth_db

# Check Prisma migrations
pnpm prisma:migrate status

# Reset database (development only)
pnpm prisma:reset
```

### Token Validation Failures
```bash
# Check JWT secret configuration
echo $JWT_SECRET_ACCESS

# Verify token expiration
# Decode JWT at jwt.io

# Check Redis session
redis-cli -p 6379 keys "session:*"
```

---

## 📚 Related Documentation

- [Architecture Overview](../../docs/ARCHITECTURE.md)
- [API Documentation](#api-endpoints) (see above)
- [Prisma Schema](../../shared/prisma/schema.prisma)
- [Email Templates](./emails/)

---

**Built with ❤️ for secure authentication**
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

