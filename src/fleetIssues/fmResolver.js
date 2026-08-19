const db = require('./db');
const config = require('../config');

/**
 * Resolve the Fleet Manager responsible for a vehicle:
 *   vehicle_number -> latest trip in the lookback window -> its service_id
 *   -> services_incharge.fleet_manager_id
 *
 * The "which trip wins" rule lives entirely in this one query (ORDER BY
 * departure_datetime DESC LIMIT 1), so swapping it for a different strategy
 * later (majority service, latest completed trip, trip frequency — spec
 * section 12) means changing this function only, not any caller.
 *
 * Never guesses: returns a `unmappedReason` instead of a fleetManagerId
 * whenever a trip or an FM mapping can't be found (spec section 13).
 */
async function resolveFleetManager(vehicleNumber) {
  const lookbackDays = config.fleetIssues.tripLookbackDays;
  const since = new Date(Date.now() - lookbackDays * 24 * 60 * 60 * 1000).toISOString();

  const trips = await db.query('trips', {
    select: 'trip_id,service_id,vehicle_number,trip_status,departure_datetime',
    filters: {
      vehicle_number: `eq.${vehicleNumber}`,
      departure_datetime: `gte.${since}`,
      service_id: 'not.is.null',
    },
    order: 'departure_datetime.desc',
    limit: 1,
  });

  if (!trips.length) {
    return {
      fleetManagerId: null,
      unmappedReason: `No trip found for vehicle in last ${lookbackDays} days`,
    };
  }

  const trip = trips[0];
  const services = await db.query('services_incharge', {
    select: 'service_id,fleet_manager_id',
    filters: { service_id: `eq.${trip.service_id}` },
    limit: 1,
  });

  if (!services.length || !services[0].fleet_manager_id) {
    return {
      fleetManagerId: null,
      serviceId: trip.service_id,
      tripId: trip.trip_id,
      unmappedReason: 'No fleet manager mapping for service',
    };
  }

  return {
    fleetManagerId: services[0].fleet_manager_id,
    serviceId: trip.service_id,
    tripId: trip.trip_id,
    unmappedReason: null,
  };
}

module.exports = { resolveFleetManager };
