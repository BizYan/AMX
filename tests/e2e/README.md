# End-to-End Tests

This directory contains end-to-end tests for the Consultant AI Workbench platform.

## Test Coverage

### API Endpoints

- **Identity & Authentication**
  - User registration and login
  - JWT token generation and validation
  - Password reset flows
  - Session management

- **Projects**
  - Project CRUD operations
  - Member management
  - Project permissions

- **Documents**
  - Document creation and retrieval
  - Document versioning
  - Document search
  - Document import/export (Word, Markdown, PPTX)

- **Knowledge & RAG**
  - Knowledge base operations
  - Vector search
  - GraphRAG queries
  - Lineage tracking

- **Agent**
  - Agent task creation
  - Workflow execution
  - Skill invocation
  - Tool execution

### Full Chain E2E Test

The `test_full_chain.py` file contains comprehensive E2E tests for the complete document lifecycle:

- **test_full_document_lifecycle**: Upload materials → Generate document → Review → Export → Audit
- **test_knowledge_graph_integration**: Knowledge entries and linking
- **test_quota_usage_tracking**: Real usage stats and rate limits API
- **test_document_generation_status_tracking**: generation_status field validation
- **test_alert_notification_retry**: Notification retry mechanism

### Critical User Journeys

1. **User Registration & Project Creation**
   - Register new user
   - Create first project
   - Invite team members

2. **Document Lifecycle**
   - Upload/create document
   - Edit and save
   - View version history
   - Export to various formats

3. **Knowledge Enhancement**
   - Add document to knowledge base
   - Perform RAG query
   - Verify vector similarity

4. **Agent Workflow**
   - Create agent task
   - Execute workflow
   - Monitor progress
   - Retrieve results

5. **Change Management**
   - Create change request
   - Apply field patches
   - Verify traceability

## Running Tests

### Prerequisites

1. Start the infrastructure:
```bash
cd infra
docker compose up -d
```

2. Wait for services to be healthy:
```bash
docker compose ps
```

### Running E2E Tests

```bash
# Run all E2E tests
pytest tests/e2e/ -v

# Run specific test file
pytest tests/e2e/test_identity.py -v

# Run specific chain test
pytest tests/e2e/test_full_chain.py -v

# Run with coverage
pytest tests/e2e/ -v --cov=apps/api
```

### Test Environment Variables

Ensure these are set in your `.env`:

```bash
DATABASE_URL=postgresql+asyncpg://consultant:consultant123@localhost:5432/consultant_ai
REDIS_URL=redis://localhost:6379/0
ARQ_REDIS_URL=redis://localhost:6379/1
JWT_SECRET_KEY=your-test-secret-key
OPENAI_API_KEY=your-api-key
```

## Integration with CI/CD

These tests are designed to run in CI/CD pipelines. They use:
- Test containers spun up via docker-compose
- Isolated test database
- Randomized test data to prevent pollution

### Playwright E2E Tests (Optional)

For browser-based E2E testing with Playwright:

```bash
# Install Playwright
npm install -D @playwright/test
npx playwright install chromium

# Run Playwright tests
cd apps/web
npx playwright test tests/e2e/playwright/
```

The main Playwright E2E test files are:
- `apps/web/tests/e2e/playwright/appendix-b.spec.ts` - Complete E2E验收测试 (Appendix B)
- `apps/web/tests/e2e/playwright/document-lifecycle.spec.ts` - Document lifecycle tests

Configure via `apps/web/playwright.config.ts`.

## Notes

- E2E tests require running infrastructure (PostgreSQL, Redis)
- Use separate test database to avoid data pollution
- Each test file can be run independently
- Mark slow tests with `@pytest.mark.slow` for selective execution