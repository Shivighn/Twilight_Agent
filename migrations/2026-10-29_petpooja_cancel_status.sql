-- Petpooja Captain Order Automation — add a cancellable status
-- Run against the SAME Supabase project as the two prior petpooja_captain_orders
-- migrations (dxcmvzlfvwtpsejkmpoy). Adding an enum value is non-breaking and
-- safe to re-run (guarded by the duplicate_object exception).
--
-- 'cancelled' means: someone sent "cancel <orderID>" on WhatsApp and we
-- recorded it — NOT that Petpooja's POS was actually told to void the
-- ticket. The real Petpooja API has no remote cancel/void endpoint (push-only
-- for order creation; see providers/petpooja_order_provider.py's docstring),
-- so this is a bookkeeping status only. The driver is told to also inform
-- kitchen staff directly, since preparation may already be underway.

do $$ begin
  alter type petpooja_order_status_enum add value 'cancelled';
exception when duplicate_object then null;
end $$;

-- Simple sequential number shown to drivers instead of Petpooja's long
-- orderID (and used to look up an order for "cancel <N>") — assigned in
-- application code only when an order actually succeeds (petty-cash-style
-- chit-chat and needs_review rows in this table never consume a number).
alter table petpooja_captain_orders add column if not exists order_no integer;
