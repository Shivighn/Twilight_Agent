-- Terminal 44 "hard rule" fix.
--
-- Callers (src/t44Buses/index.js, scripts/t44_ac_sales_report.py) already
-- send p_from/p_to as full ISO timestamps for the window they want — they
-- do NOT send plain dates, so this function's signature stays timestamptz,
-- same as it is today. What changes is only:
--   1. filter on scheduled_arrival (check-in) instead of checkout_time
--   2. the returned "date" column is the ARRIVAL's operational day
--      (4:00 AM IST cutoff), not the checkout's calendar date
-- The 4 AM-vs-old-6 AM window shift itself is done by the CALLER when it
-- builds p_from/p_to (see the Python/Node changes that go with this SQL).
CREATE OR REPLACE FUNCTION public.t44_bus_bay_report(p_from timestamptz, p_to timestamptz)
RETURNS TABLE (
  date text,
  bus_number text,
  bay text,
  operator text,
  route text,
  service_id text,
  arrival text,
  departure text,
  stopped text
)
LANGUAGE sql
AS $$
  SELECT
    TO_CHAR(((b.scheduled_arrival AT TIME ZONE 'Asia/Kolkata') - interval '4 hours')::date, 'DD Mon YYYY') AS date,
    b.bus_number,
    b.bay_no AS bay,
    topr.name AS operator,
    tr.route_to AS route,
    ts.name AS service_id,
    TO_CHAR(b.scheduled_arrival AT TIME ZONE 'Asia/Kolkata', 'FMHH12:MI AM') AS arrival,
    TO_CHAR(b.checkout_time AT TIME ZONE 'Asia/Kolkata', 'FMHH12:MI AM') AS departure,
    ROUND(EXTRACT(EPOCH FROM (b.checkout_time - b.scheduled_arrival)) / 60.0) || ' min' AS stopped
  FROM terminal_bus_bay_display b
  JOIN terminal_routes tr ON tr.id = b.route_id
  JOIN terminal_services ts ON ts.id = b.service_id
  JOIN terminal_operators topr ON topr.id = b.operator_id
  WHERE b.scheduled_arrival >= p_from
    AND b.scheduled_arrival < p_to
    AND b.status = 'departed'
  ORDER BY b.scheduled_arrival;
$$;
