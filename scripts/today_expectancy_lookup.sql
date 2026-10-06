CREATE OR REPLACE FUNCTION public.today_expectancy_lookup(p_bus_numbers text[])
RETURNS TABLE (
  bus_number text,
  operator text,
  service_number text,
  route text,
  last_check_in timestamptz
)
LANGUAGE sql
AS $$
  -- terminal_bus_bay_display keeps one row per visit, not per bus — a bus
  -- that's stopped here many times has many historical rows. DISTINCT ON
  -- picks only each bus's MOST RECENT row (highest scheduled_arrival);
  -- the outer ORDER BY then re-sorts the deduplicated result chronologically.
  SELECT * FROM (
    SELECT DISTINCT ON (t.bus_number)
      t.bus_number,
      o.name AS operator,
      s.id::text AS service_number,
      r.route_to AS route,
      t.scheduled_arrival AS last_check_in
    FROM terminal_bus_bay_display t
    LEFT JOIN terminal_operators o ON t.operator_id = o.id
    LEFT JOIN terminal_services s ON t.service_id = s.id
    LEFT JOIN terminal_routes r ON t.route_id = r.id
    WHERE t.bus_number = ANY(p_bus_numbers)
    ORDER BY t.bus_number, t.scheduled_arrival DESC
  ) latest
  ORDER BY last_check_in;
$$;
