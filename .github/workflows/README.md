# GitHub Actions CI/CD

This directory contains GitHub Actions workflows for continuous integration and deployment.

## Workflows

Each service has its own workflow file for clear error tracking and independent execution.

### `frontend.yml` - Frontend CI
- **Triggers**: Changes to `apps/frontend/**`, `packages/**`, `shared/**`, or dependency files
- **Jobs**:
  - Builds the Next.js frontend application
  - Runs linting (non-blocking)
  - Uses pnpm for package management

### `auth-server.yml` - Auth Server CI
- **Triggers**: Changes to `apps/auth_server/**`, `shared/**`, `middleware/**`, or dependency files
- **Jobs**:
  - Sets up PostgreSQL and Redis services
  - Generates Prisma client
  - Builds TypeScript code
  - Runs test suite using `tsx --test`

### `portfolio-server.yml` - Portfolio Server CI
- **Triggers**: Changes to `apps/portfolio-server/**`, `shared/py/**`, `middleware/py/**`, or requirements files
- **Jobs**:
  - Sets up PostgreSQL and Redis services
  - Installs Python dependencies
  - Generates Prisma client
  - Runs pytest test suite with coverage
  - Uploads coverage reports to Codecov

### `docker-build.yml` - Docker Build CI
- **Triggers**: Changes to Dockerfiles, `.dockerignore` files, or `docker-compose.yml`
- **Jobs**:
  - Builds frontend Docker image
  - Builds auth server Docker image
  - Builds portfolio server Docker image
  - Uses Docker Buildx with GitHub Actions cache
  - Can be manually triggered via `workflow_dispatch`

## Running Tests Locally

### Frontend
```bash
cd apps/frontend
pnpm run build
pnpm run lint
```

### Auth Server
```bash
cd apps/auth_server
pnpm install
pnpm run prisma:generate
pnpm run test
```

### Portfolio Server
```bash
cd apps/portfolio-server
pip install -r requirements.txt -r requirements-test.txt
python -m prisma generate
pnpm run test          # Run tests
pnpm run test:cov      # Run tests with coverage
```

## Environment Variables

The CI workflow uses test-specific environment variables:
- Database credentials for test databases
- Redis connection details
- API keys (dummy values for testing)
- Service URLs (localhost for testing)

## Coverage Reports

Portfolio server test coverage is uploaded to Codecov. View reports at:
- https://codecov.io/gh/YOUR_ORG/YOUR_REPO

## Troubleshooting

### Tests failing in CI but passing locally
- Check that all environment variables are set correctly
- Verify database migrations are applied
- Ensure all dependencies are installed

### Docker builds failing
- Check Dockerfile paths are correct
- Verify build context includes all necessary files
- Check for missing dependencies in Dockerfiles

