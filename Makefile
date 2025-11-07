.PHONY: help build up down restart logs ps clean migrate-deploy migrate-dev db-shell redis-shell health backup-db debug

# Default target
help:
	@echo "Auth Server Docker Compose Commands"
	@echo ""
	@echo "Setup & Build:"
	@echo "  make build          - Build the auth_server Docker image"
	@echo "  make up             - Start all services"
	@echo "  make down           - Stop all services"
	@echo "  make restart        - Restart all services"
	@echo "  make debug          - Start with debug tools (pgAdmin + Redis Commander)"
	@echo ""
	@echo "Database:"
	@echo "  make migrate-deploy - Run database migrations (production)"
	@echo "  make migrate-dev    - Create and run new migration (development)"
	@echo "  make db-shell       - Access PostgreSQL CLI"
	@echo "  make backup-db      - Backup PostgreSQL database"
	@echo ""
	@echo "Redis:"
	@echo "  make redis-shell    - Access Redis CLI"
	@echo "  make redis-monitor  - Monitor Redis commands"
	@echo ""
	@echo "Monitoring:"
	@echo "  make logs           - View logs from all services"
	@echo "  make logs-auth      - View auth_server logs"
	@echo "  make logs-db        - View PostgreSQL logs"
	@echo "  make logs-redis     - View Redis logs"
	@echo "  make ps             - Show running containers"
	@echo "  make health         - Check service health"
	@echo "  make stats          - Show container stats"
	@echo ""
	@echo "Cleanup:"
	@echo "  make clean          - Stop and remove all containers and volumes"
	@echo "  make clean-build    - Clean and rebuild everything"

# Build auth_server image
build:
	@echo "🏗️  Building auth_server Docker image..."
	docker build -f apps/auth_server/Dockerfile -t auth_server:latest .

# Start all services
up:
	@echo "🚀 Starting all services..."
	docker-compose up -d
	@echo "✅ Services started! Run 'make logs' to view logs"
	@echo "⚠️  Don't forget to run 'make migrate-deploy' if this is first time setup"

# Start with debug tools
debug:
	@echo "🚀 Starting all services with debug tools..."
	docker-compose --profile debug up -d
	@echo "✅ Services started!"
	@echo "📊 pgAdmin: http://localhost:5050 (admin@example.com / admin)"
	@echo "📊 Redis Commander: http://localhost:8081"
	@echo "🔗 Auth Server: http://localhost:4000"

# Stop all services
down:
	@echo "🛑 Stopping all services..."
	docker-compose down

# Restart all services
restart:
	@echo "🔄 Restarting all services..."
	docker-compose restart

# View logs from all services
logs:
	docker-compose logs -f

# View auth_server logs
logs-auth:
	docker-compose logs -f auth_server

# View PostgreSQL logs
logs-db:
	docker-compose logs -f postgres

# View Redis logs
logs-redis:
	docker-compose logs -f redis

# Show running containers
ps:
	docker-compose ps

# Run database migrations (production)
migrate-deploy:
	@echo "🗄️  Running database migrations..."
	docker-compose exec auth_server npx prisma migrate deploy
	@echo "✅ Migrations completed!"

# Create new migration (development)
migrate-dev:
	@read -p "Enter migration name: " migration_name; \
	docker-compose exec auth_server npx prisma migrate dev --name $$migration_name

# Access PostgreSQL shell
db-shell:
	@echo "📊 Accessing PostgreSQL shell..."
	@echo "Commands: \\dt (list tables), \\d table_name (describe table), \\q (quit)"
	docker-compose exec postgres psql -U auth_user -d auth_db

# Access Redis CLI
redis-shell:
	@echo "📊 Accessing Redis CLI..."
	@echo "Commands: KEYS *, GET key, SET key value, QUIT"
	docker-compose exec redis redis-cli

# Monitor Redis commands
redis-monitor:
	@echo "📊 Monitoring Redis commands (Ctrl+C to stop)..."
	docker-compose exec redis redis-cli monitor

# Check service health
health:
	@echo "🏥 Checking service health..."
	@echo ""
	@echo "PostgreSQL:"
	@docker-compose exec postgres pg_isready -U auth_user -d auth_db || echo "❌ PostgreSQL is not ready"
	@echo ""
	@echo "Redis:"
	@docker-compose exec redis redis-cli ping || echo "❌ Redis is not ready"
	@echo ""
	@echo "Auth Server:"
	@curl -s http://localhost:4000/health > /dev/null && echo "✅ Auth Server is healthy" || echo "❌ Auth Server is not responding"

# Show container stats
stats:
	docker stats auth_server postgres redis --no-stream

# Backup database
backup-db:
	@echo "💾 Creating database backup..."
	@mkdir -p backups
	docker-compose exec postgres pg_dump -U auth_user auth_db > backups/backup_$$(date +%Y%m%d_%H%M%S).sql
	@echo "✅ Backup created in backups/ directory"

# Clean everything (removes volumes!)
clean:
	@echo "⚠️  This will remove all containers and volumes (data will be lost!)"
	@read -p "Are you sure? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		docker-compose down -v; \
		echo "✅ Cleanup completed"; \
	else \
		echo "❌ Cleanup cancelled"; \
	fi

# Clean and rebuild everything
clean-build: clean build up migrate-deploy
	@echo "✅ Clean build completed!"
	@echo "🔗 Auth Server: http://localhost:4000"

# First time setup
setup: build up
	@echo "⏳ Waiting for services to be ready (15 seconds)..."
	@sleep 15
	@echo "🗄️  Running database migrations..."
	@make migrate-deploy
	@echo ""
	@echo "✅ Setup completed!"
	@echo "🔗 Auth Server: http://localhost:4000"
	@echo "📖 Run 'make help' for more commands"
