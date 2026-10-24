Design a production-ready **Petpooja Captain Order Automation** module inside the existing AI agent.

**Current workflow:** Drivers send WhatsApp group messages ~20 minutes before reaching the restaurant, containing vehicle number, passenger count, and food items/quantities. Example: `AP39UX7896, 3 people, 1 Chicken Biryani, 2 Roti...`. Currently, a user manually enters each item into the Petpooja Captain app, causing delays.

**Goal:** Automatically read messages from the designated WhatsApp group, parse and validate orders using AI/rule-based parsing, create orders directly in Petpooja, and persist every order and its processing status in Supabase. The live dashboard will be developed later.

### Requirements

1. **WhatsApp integration:** Reuse the existing WhatsApp agent and group-monitoring infrastructure. Process only the configured group; capture message ID, sender, timestamp, and original text.

2. **Modular Petpooja integration:** Create a provider-independent order service with a `PetpoojaOrderProvider` interface/adapter. Initially, implement a mock/dry-run adapter because the exact Petpooja Orders API is not yet available. Keep all API-specific logic, authentication, payload mapping, and response handling isolated so the real API can be integrated later without changing the business logic or database schema. Do not assume undocumented endpoints exist.

3. **Order parsing and validation:** Extract vehicle number, passenger(drivers, helpers, not onboard passengers) count, item names, and quantities. Match food items against a configurable Petpooja menu/catalogue. If an item is ambiguous, unavailable, or unmatched, flag the order for manual review rather than guessing. Support multiple items and quantities.

4. **Supabase database:** Define the complete database architecture, including tables, columns, types, primary/foreign keys, unique constraints, indexes, timestamps, processing statuses, error details, and migration SQL. Store incoming messages, parsed orders, order items, Petpooja order IDs/responses, and processing attempts. Ensure the schema supports future dashboard queries and reconciliation.(no unnecessary tables required, if it can be done simply in 1 table that's also fine)

5. **Reliability and duplicate prevention:** Enforce idempotency using WhatsApp message IDs and prevent duplicate Petpooja orders during retries, restarts, or network timeouts. Use a transactional outbox/job mechanism or equivalent reliable processing design. Never blindly retry an order creation when the previous request may have succeeded; reconcile first when possible. Track failures and provide safe retry/manual-review mechanisms.

6. **Zero-downtime integration:** Add this as an isolated module without disrupting existing WhatsApp listeners, scheduled jobs, or agent services. Use feature flags, backward-compatible migrations, graceful startup/shutdown, bounded retries, structured logs, and health checks. Do not replace or restart unrelated services unnecessarily. Explain how to deploy and roll back safely.

7. **Single-file architecture document:** Put the entire proposed architecture, database design, SQL migration, processing flow, provider interface, configuration/environment variables, failure scenarios, security considerations, implementation phases, and testing strategy in **one clearly organized Markdown file** in the repository. Keep actual production code modular; do not force the entire implementation into one source file.

8. **Testing and activation:** Include unit tests for message parsing, menu matching, validation, idempotency, retries, and provider failures. Initially run in dry-run mode and verify parsed orders and Supabase records without creating real Petpooja orders. Enable real order creation only after the official API documentation, credentials, and test results are verified.

**First inspect the existing repository** to understand its WhatsApp listener, agent architecture, Supabase conventions, environment configuration, and deployment setup. Reuse existing patterns instead of duplicating infrastructure.

**For this task, focus on the architecture and database design document only.** Do not implement real order creation or modify existing production behavior yet. Keep the design easy to extend when the official Petpooja Orders API becomes available.