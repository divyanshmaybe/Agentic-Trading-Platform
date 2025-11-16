.PHONY: help build build-auth build-portfolio build-frontend build-all up down restart logs ps clean migrate-deploy migrate-dev db-shell portfolio-db-shell redis-shell portfolio-redis-shell health backup-db debug

# Default target
help:
	@echo "Docker Compose Commands - Agent Invest Platform"
	@echo ""
	@echo "Setup & Build:"
	@echo "  make build            - Build all Docker images"
	@echo "  make build-auth       - Build auth_server image only"
	@echo "  make build-portfolio  - Build portfolio_server image only"
	@echo "  make build-frontend   - Build frontend image only"
	@echo "  make build-all        - Build all service images"
	@echo "  make up               - Start all services"
	@echo "  make down             - Stop all services"
	@echo "  make restart          - Restart all services"
	@echo "  make debug            - Start with debug tools (pgAdmin + Redis Commander)"
	@echo ""
	@echo "Database:"
	@echo "  make migrate-deploy   - Run auth_server database migrations"
	@echo "  make migrate-dev      - Create new auth_server migration (development)"
	@echo "  make db-shell         - Access auth PostgreSQL CLI"
	@echo "  make portfolio-db-shell - Access portfolio PostgreSQL CLI"
	@echo "  make backup-db        - Backup auth PostgreSQL database"
	@echo "  make backup-portfolio-db - Backup portfolio PostgreSQL database"
	@echo ""
	@echo "Redis:"
	@echo "  make redis-shell      - Access auth Redis CLI"
	@echo "  make portfolio-redis-shell - Access portfolio Redis CLI"
	@echo "  make redis-monitor    - Monitor auth Redis commands"
	@echo "  make portfolio-redis-monitor - Monitor portfolio Redis commands"
	@echo ""
	@echo "Monitoring:"
	@echo "  make logs             - View logs from all services"
	@echo "  make logs-auth        - View auth_server logs"
	@echo "  make logs-portfolio   - View portfolio_server logs"
	@echo "  make logs-celery      - View portfolio_celery logs"
	@echo "  make logs-frontend    - View frontend logs"
	@echo "  make logs-kafka       - View kafka logs"
	@echo "  make logs-db          - View auth PostgreSQL logs"
	@echo "  make logs-portfolio-db - View portfolio PostgreSQL logs"
	@echo "  make logs-redis       - View auth Redis logs"
	@echo "  make logs-portfolio-redis - View portfolio Redis logs"
	@echo "  make ps               - Show running containers"
	@echo "  make health           - Check service health"
	@echo "  make stats            - Show container stats"
	@echo ""
	@echo "Celery:"
	@echo "  make celery-shell     - Access Celery shell (portfolio_celery)"
	@echo "  make celery-restart   - Restart Celery worker"
	@echo ""
	@echo "Kafka:"
	@echo "  make kafka-topics     - List Kafka topics"
	@echo "  make kafka-console-producer - Start Kafka console producer"
	@echo "  make kafka-console-consumer - Start Kafka console consumer"
	@echo ""
	@echo "Cleanup:"
	@echo "  make clean            - Stop and remove all containers and volumes"
	@echo "  make clean-build      - Clean and rebuild everything"

# Build all images
build: build-all

# Build auth_server image
build-auth:
	@echo "🏗️  Building auth_server Docker image..."
	docker build -f apps/auth_server/Dockerfile -t auth_server:latest .

# Build portfolio_server image
build-portfolio:
	@echo "🏗️  Building portfolio_server Docker image..."
	docker build -f apps/portfolio-server/Dockerfile -t portfolio_server:latest .

# Build frontend image
build-frontend:
	@echo "🏗️  Building frontend Docker image..."
	docker build -f apps/frontend/Dockerfile -t frontend_web:latest .

# Build all service images
build-all: build-auth build-portfolio build-frontend
	@echo "✅ All images built successfully!"

# Start all services
up:
	@echo "🚀 Starting all services..."
	docker-compose up -d
	@echo "✅ Services started! Run 'make logs' to view logs"
	@echo "⚠️  Don't forget to run 'make migrate-deploy' if this is first time setup"
	@echo ""
	@echo "🔗 Services:"
	@echo "  - Auth Server: http://localhost:4000"
	@echo "  - Portfolio Server: http://localhost:8000"
	@echo "  - Frontend: http://localhost:3000"
	@echo "  - Kafka: localhost:9092"

# Start with debug tools
debug:
	@echo "🚀 Starting all services with debug tools..."
	docker-compose --profile debug up -d
	@echo "✅ Services started!"
	@echo ""
	@echo "🔗 Services:"
	@echo "  - Auth Server: http://localhost:4000"
	@echo "  - Portfolio Server: http://localhost:8000"
	@echo "  - Frontend: http://localhost:3000"
	@echo ""
	@echo "📊 Debug Tools:"
	@echo "  - pgAdmin: http://localhost:5050 (admin@example.com / admin)"
	@echo "  - Redis Commander: http://localhost:8081"

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

# View portfolio_server logs
logs-portfolio:
	docker-compose logs -f portfolio_server

# View portfolio_celery logs
logs-celery:
	docker-compose logs -f portfolio_celery

# View frontend logs
logs-frontend:
	docker-compose logs -f frontend

# View kafka logs
logs-kafka:
	docker-compose logs -f kafka

# View auth PostgreSQL logs
logs-db:
	docker-compose logs -f postgres

# View portfolio PostgreSQL logs
logs-portfolio-db:
	docker-compose logs -f portfolio_postgres

# View auth Redis logs
logs-redis:
	docker-compose logs -f redis

# View portfolio Redis logs
logs-portfolio-redis:
	docker-compose logs -f portfolio_redis

# Show running containers
ps:
	docker-compose ps

# Run database migrations (production) - Auth Server
migrate-deploy:
	@echo "🗄️  Running auth_server database migrations..."
	docker-compose exec auth_server npx prisma migrate deploy
	@echo "✅ Migrations completed!"

# Create new migration (development) - Auth Server
migrate-dev:
	@read -p "Enter migration name: " migration_name; \
	docker-compose exec auth_server npx prisma migrate dev --name $$migration_name

# Access auth PostgreSQL shell
db-shell:
	@echo "📊 Accessing auth PostgreSQL shell..."
	@echo "Commands: \\dt (list tables), \\d table_name (describe table), \\q (quit)"
	docker-compose exec postgres psql -U auth_user -d auth_db

# Access portfolio PostgreSQL shell
portfolio-db-shell:
	@echo "📊 Accessing portfolio PostgreSQL shell..."
	@echo "Commands: \\dt (list tables), \\d table_name (describe table), \\q (quit)"
	docker-compose exec portfolio_postgres psql -U portfolio_user -d portfolio_db

# Access auth Redis CLI
redis-shell:
	@echo "📊 Accessing auth Redis CLI..."
	@echo "Commands: KEYS *, GET key, SET key value, QUIT"
	docker-compose exec redis redis-cli

# Access portfolio Redis CLI
portfolio-redis-shell:
	@echo "📊 Accessing portfolio Redis CLI..."
	@echo "Commands: KEYS *, GET key, SET key value, QUIT"
	docker-compose exec portfolio_redis redis-cli

# Monitor auth Redis commands
redis-monitor:
	@echo "📊 Monitoring auth Redis commands (Ctrl+C to stop)..."
	docker-compose exec redis redis-cli monitor

# Monitor portfolio Redis commands
portfolio-redis-monitor:
	@echo "📊 Monitoring portfolio Redis commands (Ctrl+C to stop)..."
	docker-compose exec portfolio_redis redis-cli monitor

# Access Celery shell
celery-shell:
	@echo "📊 Accessing Celery shell..."
	docker-compose exec portfolio_celery python -c "from celery_app import celery_app; celery_app.control.inspect().active()"

# Restart Celery worker
celery-restart:
	@echo "🔄 Restarting Celery worker..."
	docker-compose restart portfolio_celery

# List Kafka topics
kafka-topics:
	@echo "📊 Listing Kafka topics..."
	docker-compose exec kafka kafka-topics.sh --bootstrap-server localhost:9092 --list

# Kafka console producer
kafka-console-producer:
	@read -p "Enter topic name: " topic; \
	docker-compose exec -it kafka kafka-console-producer.sh --bootstrap-server localhost:9092 --topic $$topic

# Kafka console consumer
kafka-console-consumer:
	@read -p "Enter topic name: " topic; \
	docker-compose exec -it kafka kafka-console-consumer.sh --bootstrap-server localhost:9092 --topic $$topic --from-beginning

# Check service health
health:
	@echo "🏥 Checking service health..."
	@echo ""
	@echo "Auth PostgreSQL:"
	@docker-compose exec postgres pg_isready -U auth_user -d auth_db || echo "❌ Auth PostgreSQL is not ready"
	@echo ""
	@echo "Portfolio PostgreSQL:"
	@docker-compose exec portfolio_postgres pg_isready -U portfolio_user -d portfolio_db || echo "❌ Portfolio PostgreSQL is not ready"
	@echo ""
	@echo "Auth Redis:"
	@docker-compose exec redis redis-cli ping || echo "❌ Auth Redis is not ready"
	@echo ""
	@echo "Portfolio Redis:"
	@docker-compose exec portfolio_redis redis-cli ping || echo "❌ Portfolio Redis is not ready"
	@echo ""
	@echo "Kafka:"
	@docker-compose exec kafka kafka-topics.sh --bootstrap-server localhost:9092 --list >/dev/null 2>&1 && echo "✅ Kafka is healthy" || echo "❌ Kafka is not ready"
	@echo ""
	@echo "Auth Server:"
	@curl -s http://localhost:4000/health >/dev/null && echo "✅ Auth Server is healthy" || echo "❌ Auth Server is not responding"
	@echo ""
	@echo "Portfolio Server:"
	@curl -s http://localhost:8000/health >/dev/null && echo "✅ Portfolio Server is healthy" || echo "❌ Portfolio Server is not responding"
	@echo ""
	@echo "Frontend:"
	@curl -s http://localhost:3000 >/dev/null && echo "✅ Frontend is healthy" || echo "❌ Frontend is not responding"

# Show container stats
stats:
	docker stats --no-stream auth_server portfolio_server portfolio_celery frontend postgres portfolio_postgres redis portfolio_redis kafka 2>/dev/null || docker stats --no-stream

# Backup auth database
backup-db:
	@echo "💾 Creating auth database backup..."
	@mkdir -p backups
	docker-compose exec postgres pg_dump -U auth_user auth_db > backups/auth_backup_$$(date +%Y%m%d_%H%M%S).sql
	@echo "✅ Backup created in backups/ directory"

# Backup portfolio database
backup-portfolio-db:
	@echo "💾 Creating portfolio database backup..."
	@mkdir -p backups
	docker-compose exec portfolio_postgres pg_dump -U portfolio_user portfolio_db > backups/portfolio_backup_$$(date +%Y%m%d_%H%M%S).sql
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
clean-build: clean build-all up
	@echo "⏳ Waiting for services to be ready (20 seconds)..."
	@sleep 20
	@echo "🗄️  Running database migrations..."
	@make migrate-deploy
	@echo ""
	@echo "✅ Clean build completed!"
	@echo ""
	@echo "🔗 Services:"
	@echo "  - Auth Server: http://localhost:4000"
	@echo "  - Portfolio Server: http://localhost:8000"
	@echo "  - Frontend: http://localhost:3000"

# First time setup
setup: build-all up
	@echo "⏳ Waiting for services to be ready (20 seconds)..."
	@sleep 20
	@echo "🗄️  Running database migrations..."
	@make migrate-deploy
	@echo ""
	@echo "✅ Setup completed!"
	@echo ""
	@echo "🔗 Services:"
	@echo "  - Auth Server: http://localhost:4000"
	@echo "  - Portfolio Server: http://localhost:8000"
	@echo "  - Frontend: http://localhost:3000"
	@echo ""
	@echo "📖 Run 'make help' for more commands"
