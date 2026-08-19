/**
 * Supabase data access via direct PostgREST calls (axios) — mirrors the
 * pattern already established in agent/db.py (Python side) for the same
 * project: talk to PostgREST directly with the service-role key rather than
 * a Supabase SDK, and hard-block any method/route this agent must never use.
 */

const axios = require('axios');
const config = require('../config');

function assertConfigured() {
  if (!config.supabase.url || !config.supabase.serviceRoleKey) {
    throw new Error(
      'SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set — fleet issue agent cannot reach the database'
    );
  }
}

function client() {
  assertConfigured();
  const instance = axios.create({
    baseURL: `${config.supabase.url}/rest/v1`,
    timeout: 30000,
    headers: {
      apikey: config.supabase.serviceRoleKey,
      Authorization: `Bearer ${config.supabase.serviceRoleKey}`,
      'Content-Type': 'application/json',
    },
  });

  // Delete guardrail — mirrors agent/db.py's _guard_request. This agent may
  // read (GET), create (POST) and update (PATCH) — never delete, and never
  // call an RPC (which could run arbitrary server-side SQL, including
  // deletes). Enforced on every outgoing request via an interceptor so no
  // call path through this module can slip past it.
  instance.interceptors.request.use((req) => {
    const method = (req.method || 'get').toUpperCase();
    const allowed = new Set(['GET', 'POST', 'PATCH', 'HEAD']);
    if (!allowed.has(method)) {
      throw new Error(`[DB GUARD] Blocked ${method} ${req.url} — not allowed to delete data`);
    }
    if ((req.url || '').includes('/rpc/')) {
      throw new Error(`[DB GUARD] Blocked RPC call ${req.url} — not allowed to run server-side functions`);
    }
    return req;
  });

  return instance;
}

/**
 * SELECT rows from a table.
 * `filters` values are raw PostgREST operators, e.g. { status: 'eq.Open',
 * departure_datetime: 'gte.2026-08-01' } — matches how PostgREST's own query
 * syntax reads, so callers can use any operator (eq/gte/lte/in/...) directly.
 */
async function query(table, { select = '*', filters = {}, order, limit } = {}) {
  const params = { select, ...filters };
  if (order) params.order = order;
  if (limit) params.limit = limit;
  const { data } = await client().get(`/${table}`, { params });
  return data;
}

/** INSERT a single row, returning the created record. */
async function insert(table, row) {
  const { data } = await client().post(`/${table}`, row, {
    headers: { Prefer: 'return=representation' },
  });
  return data;
}

/** UPSERT a single row, updating on conflict columns. */
async function upsert(table, row, onConflict) {
  const { data } = await client().post(`/${table}`, row, {
    params: { on_conflict: onConflict },
    headers: { Prefer: 'resolution=merge-duplicates,return=representation' },
  });
  return data;
}

/** UPDATE (PATCH) rows matching `filters` with `patch`. */
async function update(table, filters, patch) {
  const { data } = await client().patch(`/${table}`, patch, {
    params: { ...filters },
    headers: { Prefer: 'return=representation' },
  });
  return data;
}

module.exports = { query, insert, upsert, update };
