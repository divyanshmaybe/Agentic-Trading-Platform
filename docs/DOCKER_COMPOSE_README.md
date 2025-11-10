# Docker Compose Setup for Auth Server

This Docker Compose configuration sets up the complete auth server stack with PostgreSQL and Redis.

## Services Included

### Core Services
- **auth_server**: Authentication and authorization microservice (Node.js/Express/TypeScript)
- **postgres**: PostgreSQL 16 database for persistent data storage
- **redis**: Redis 7 for caching and BullMQ job queues

### Debug Tools (Optional)
- **pgadmin**: PostgreSQL web interface (available with `--profile debug`)
- **redis-commander**: Redis web interface (available with `--profile debug`)

## Quick Start

### 1. Build the Auth Server Image
```bash
docker build -f apps/auth_server/Dockerfile -t auth_server:latest .
```

### 2. Create Environment File
Copy the example environment file and update with your values:
```bash
cp .env.example .env
# Edit .env with your actual values, especially:
# - JWT secrets (generate with: openssl rand -base64 32)
# - SENDGRID_API_KEY
# - SENDER_EMAIL_ADDRESS
```

### 3. Start All Services
```bash
docker-compose up -d
```

### 4. Run Database Migrations
After the containers are running, execute migrations:
```bash
docker-compose exec auth_server pnpm --filter auth_server prisma:migrate
```

Or use the direct Prisma command:
```bash
docker-compose exec auth_server npx prisma migrate deploy
```

## Available Commands

### Start Services
```bash
# Start all services in background
docker-compose up -d

# Start with logs in foreground
docker-compose up

# Start with debug tools (pgAdmin & Redis Commander)
docker-compose --profile debug up -d
```

### Stop Services
```bash
# Stop all services
docker-compose down

# Stop and remove volumes (⚠️ deletes all data)
docker-compose down -v
```

### View Logs
```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f auth_server
docker-compose logs -f postgres
docker-compose logs -f redis
```

### Database Management

#### Run Migrations
```bash
docker-compose exec auth_server npx prisma migrate deploy
```

#### Access PostgreSQL CLI
```bash
docker-compose exec postgres psql -U auth_user -d auth_db
```

#### Generate Prisma Client
```bash
docker-compose exec auth_server pnpm --filter auth_server prisma:generate
```

#### Create New Migration
```bash
docker-compose exec auth_server npx prisma migrate dev --name migration_name
```

### Redis Management

#### Access Redis CLI
```bash
docker-compose exec redis redis-cli
```

#### Monitor Redis Commands
```bash
docker-compose exec redis redis-cli monitor
```

#### Check Redis Stats
```bash
docker-compose exec redis redis-cli INFO
```

### Service Health Checks
```bash
# Check status of all containers
docker-compose ps

# Check health of specific service
docker inspect --format='{{.State.Health.Status}}' auth_server
```

### Restart Services
```bash
# Restart all services
docker-compose restart

# Restart specific service
docker-compose restart auth_server
```

### Rebuild and Restart
```bash
# Rebuild auth_server and restart
docker-compose up -d --build auth_server
```

## Service Access

### Application Endpoints
- **Auth Server**: http://localhost:4000
- **Health Check**: http://localhost:4000/health

### Database Connections
- **PostgreSQL**: 
  - Host: localhost
  - Port: 5432
  - Database: auth_db
  - User: auth_user
  - Password: auth_password (change in production!)

- **Redis**:
  - Host: localhost
  - Port: 6379
  - URL: redis://localhost:6379

### Debug Tools (with --profile debug)
- **pgAdmin**: http://localhost:5050
  - Email: admin@example.com
  - Password: admin
  
- **Redis Commander**: http://localhost:8081

## Production Considerations

### Security
1. **Change all default passwords and secrets!**
   ```bash
   # Generate secure secrets
   openssl rand -base64 32
   ```

2. **Update credentials in .env:**
   - JWT_SECRET_ACCESS
   - JWT_SECRET_REFRESH
   - JWT_SECRET_EMAIL
   - INTERNAL_SERVICE_SECRET
   - SESSION_SECRET
   - PostgreSQL password

3. **Use Docker secrets or environment variable injection** for sensitive data

### Performance
1. **Adjust Redis memory limits** in docker-compose.yml:
   ```yaml
   command: redis-server --appendonly yes --maxmemory 512mb --maxmemory-policy allkeys-lru
   ```

2. **Scale workers** if needed:
   ```yaml
   environment:
     EMAIL_WORKER_CONCURRENCY: 20
   ```

3. **PostgreSQL tuning** - mount custom postgresql.conf:
   ```yaml
   volumes:
     - ./postgres.conf:/etc/postgresql/postgresql.conf
   ```

### Backups

#### PostgreSQL Backup
```bash
# Create backup
docker-compose exec postgres pg_dump -U auth_user auth_db > backup_$(date +%Y%m%d_%H%M%S).sql

# Restore backup
docker-compose exec -T postgres psql -U auth_user auth_db < backup.sql
```

#### Redis Backup
```bash
# Create backup (Redis uses AOF persistence)
docker-compose exec redis redis-cli BGSAVE

# Copy backup file
docker cp auth_redis:/data/dump.rdb ./redis_backup_$(date +%Y%m%d_%H%M%S).rdb
```

## Troubleshooting

### Auth Server won't start
1. Check logs: `docker-compose logs auth_server`
2. Verify database connection: `docker-compose exec postgres pg_isready`
3. Ensure migrations are run: `docker-compose exec auth_server npx prisma migrate deploy`

### Database connection errors
1. Check if PostgreSQL is healthy: `docker-compose ps postgres`
2. Verify DATABASE_URL in .env matches docker-compose.yml
3. Check network connectivity: `docker-compose exec auth_server ping postgres`

### Redis connection errors
1. Check if Redis is running: `docker-compose exec redis redis-cli ping`
2. Verify REDIS_URL in .env: `redis://redis:6379`
3. Check queue logs in auth_server

### Port conflicts
If ports are already in use, modify in docker-compose.yml:
```yaml
ports:
  - "4001:4000"  # Change host port
  - "5433:5432"  # PostgreSQL on different port
  - "6380:6379"  # Redis on different port
```

### Reset Everything
```bash
# Stop and remove everything
docker-compose down -v

# Remove auth_server image
docker rmi auth_server:latest

# Rebuild and start fresh
docker build -f apps/auth_server/Dockerfile -t auth_server:latest .
docker-compose up -d
docker-compose exec auth_server npx prisma migrate deploy
```

## Development Mode

For development, you might want to:

1. **Use local code with volume mounts:**
   ```yaml
   volumes:
     - ./apps/auth_server:/app/apps/auth_server
     - ./shared:/app/shared
   ```

2. **Enable hot reload:**
   ```yaml
   command: pnpm --filter auth_server dev
   ```

3. **Use debug profile:**
   ```bash
   docker-compose --profile debug up
   ```

## Monitoring

### Container Stats
```bash
docker stats auth_server postgres redis
```

### Queue Monitoring
Access Redis Commander at http://localhost:8081 (with `--profile debug`) to view BullMQ queues.

### Database Queries
Access pgAdmin at http://localhost:5050 (with `--profile debug`) to run queries and view database structure.

## Environment Variables Reference

See `.env.example` for a complete list of required environment variables.

### Critical Variables
- `DATABASE_URL`: PostgreSQL connection string
- `REDIS_URL`: Redis connection string
- `JWT_SECRET_ACCESS`: Secret for access tokens
- `JWT_SECRET_REFRESH`: Secret for refresh tokens
- `SENDGRID_API_KEY`: Email service API key

## Network Configuration

All services are connected via `auth_network` bridge network, allowing inter-service communication using service names:
- `postgres:5432`
- `redis:6379`
- `auth_server:4000`
