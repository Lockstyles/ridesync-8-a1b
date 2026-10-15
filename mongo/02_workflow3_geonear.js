// Workflow 3 (RideSync — vehicle/location domain): Nearest Available Vehicle
//
// Given a rider's coordinates, return the closest AVAILABLE vehicles within
// 5km, using the live TelemetryPings stream.

const RIDER_LOCATION = {
  type: "Point",
  coordinates: [78.3488, 17.4454], // IIIT Hyderabad campus
};
const MAX_DISTANCE_METERS = 5000;
const RESULT_LIMIT = 5;

const pipeline = [
  {
    $geoNear: {
      near: RIDER_LOCATION,
      distanceField: "distance_m",
      maxDistance: MAX_DISTANCE_METERS,
      spherical: true,
      query: { is_available: true },
      key: "location",
    },
  },
  {
    $group: {
      _id: "$vehicle_id",
      vehicle_id: { $first: "$vehicle_id" },
      distance_m: { $first: "$distance_m" },
      location: { $first: "$location" },
      driver_id: { $first: "$driver_id" },
      speed_kmph: { $first: "$speed_kmph" },
      created_at: { $first: "$created_at" },
    },
  },
  { $sort: { distance_m: 1 } },
  { $limit: RESULT_LIMIT },
  {
    $project: {
      _id: 0,
      vehicle_id: 1,
      distance_m: { $round: ["$distance_m", 1] },
      location: 1,
      driver_id: 1,
      speed_kmph: 1,
      created_at: 1,
    },
  },
];

print("--- Workflow 3: nearest available vehicles ---");
db.TelemetryPings.aggregate(pipeline).forEach(printjson);

const explainResult =
  db.TelemetryPings.explain("executionStats").aggregate(pipeline);

const OUTPUT_PATH = "performance/mongo_execution_stats.json"; // relative to root repo
let existingStats = {};
try {
  existingStats = JSON.parse(fs.readFileSync(OUTPUT_PATH, "utf8"));
} catch (e) {
  // file doesn't exist yet, or isn't valid JSON — start fresh
}
existingStats.workflow3_geonear = explainResult;
fs.writeFileSync(OUTPUT_PATH, JSON.stringify(existingStats, null, 2));
print(`\nWrote Workflow 3 explain(executionStats) to ${OUTPUT_PATH}`);
