// Shapes returned by the Django API (see backend/routing/services/planner.py).

export type LngLat = [number, number]

/** 0 Low · 1 Moderate · 2 High · 3 Severe · 4 No Travel */
export type RiskLevel = 0 | 1 | 2 | 3 | 4

export type LevelKey = 'low' | 'moderate' | 'high' | 'severe' | 'no_travel'
export type MilesByLevel = Record<LevelKey, number>

export interface Place {
  label: string
  lat: number
  lon: number
}

export interface PlanInput {
  origin: Place
  destination: Place
  departure: string // ISO 8601
  load_lbs: number
  interval_mi: 10 | 25 | 50
  hos: boolean
}

export interface Assessment {
  level: RiskLevel
  label: string
  wind_level: RiskLevel
  rain_level: RiskLevel
  snow_level: RiskLevel
  drivers: ('wind' | 'rain' | 'snow')[]
  load_rule: string | null
}

export interface Checkpoint {
  mile: number
  lon: number
  lat: number
  eta: string
  elapsed_s: number
  owned_miles: number
  wind_mph: number
  gust_mph: number
  rain_in_hr: number
  snow_in_hr: number
  temp_f: number
  weather_code: number
  risk: Assessment
}

export interface Stop {
  kind: 'break' | 'rest'
  mile: number
  lon: number
  lat: number
  start: string
  end: string
  duration_s: number
}

export interface RiskSegment {
  level: RiskLevel
  from_mile: number
  to_mile: number
}

export interface ScanRow {
  offset_h: number
  miles_by_level: MilesByLevel
  avg_risk: number
}

export interface Route {
  id: string
  name: string
  roads: string[]
  source: 'osrm' | 'via'
  distance_mi: number
  drive_s: number
  trip_s: number
  arrival: string
  path: LngLat[]
  path_miles: number[]
  path_s: number[]
  segments: RiskSegment[]
  checkpoints: Checkpoint[]
  stops: Stop[]
  metrics: { miles_by_level: MilesByLevel; avg_risk: number; max_level: RiskLevel }
  departure_scan: ScanRow[]
}

export interface Recommendation {
  route_id: string
  ranking: string[]
  reason: string
  comparisons: Record<string, string>
  unsafe: boolean
}

export interface DepartureAdvice {
  offset_h: number
  route_id: string
  miles_by_level: MilesByLevel
  avg_risk: number
  baseline: { route_id: string; miles_by_level: MilesByLevel; avg_risk: number }
}

export interface Plan {
  inputs: PlanInput
  routes: Route[]
  recommendation: Recommendation
  departure_advice: DepartureAdvice | null
}

export type HeatLayer = 'risk' | 'wind' | 'gust' | 'rain' | 'snow'

export interface Heatmap {
  bbox: [number, number, number, number] // west, south, east, north
  cols: number
  rows: number
  cell_mi: number
  cells: number[] // flat indices (row * cols + col) inside the corridor
  times: number[] // unix seconds, 49 hourly frames
  corridor_mi: number
  layers: Record<HeatLayer, number[][]> // [frame][cell]
}
