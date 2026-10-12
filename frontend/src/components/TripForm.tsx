import { useState } from 'react'
import { nextQuarterHour, toLocalInput, localZone } from '../lib/format'
import type { Place, PlanInput } from '../types'
import PlaceInput from './PlaceInput'

const PRESETS: { name: string; origin: Place; destination: Place }[] = [
  {
    name: 'Chicago → Denver',
    origin: { label: 'Chicago, Illinois, United States', lat: 41.8756, lon: -87.6244 },
    destination: { label: 'Denver, Colorado, United States', lat: 39.7392, lon: -104.9849 },
  },
  {
    name: 'Dallas → Atlanta',
    origin: { label: 'Dallas, Texas, United States', lat: 32.7763, lon: -96.7969 },
    destination: { label: 'Atlanta, Georgia, United States', lat: 33.7489, lon: -84.3902 },
  },
  {
    name: 'Seattle → Salt Lake City',
    origin: { label: 'Seattle, Washington, United States', lat: 47.6038, lon: -122.3301 },
    destination: { label: 'Salt Lake City, Utah, United States', lat: 40.7596, lon: -111.8868 },
  },
]

const LOAD_PRESETS = [
  { label: 'Empty', lbs: 0 },
  { label: '25k', lbs: 25_000 },
  { label: '35k', lbs: 35_000 },
  { label: '44k', lbs: 44_000 },
]

interface Props {
  loading: boolean
  onSubmit: (input: PlanInput) => void
}

export default function TripForm({ loading, onSubmit }: Props) {
  const [origin, setOrigin] = useState<Place | null>(PRESETS[0].origin)
  const [destination, setDestination] = useState<Place | null>(PRESETS[0].destination)
  const [departure, setDeparture] = useState(() => toLocalInput(nextQuarterHour()))
  const [load, setLoad] = useState('42000')
  const [interval, setIntervalMi] = useState<PlanInput['interval_mi']>(25)
  const [hos, setHos] = useState(true)
  const [touched, setTouched] = useState(false)

  const loadNum = Number(load)
  const loadValid = load.trim() !== '' && Number.isFinite(loadNum) && loadNum >= 0 && loadNum <= 200_000
  const valid = origin && destination && departure && loadValid

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    setTouched(true)
    if (!valid) return
    onSubmit({
      origin,
      destination,
      departure: new Date(departure).toISOString(),
      load_lbs: loadNum,
      interval_mi: interval,
      hos,
    })
  }

  const now = new Date()
  const maxDate = new Date(now.getTime() + 7 * 24 * 3600 * 1000)

  return (
    <form className="trip-form" onSubmit={submit} noValidate>
      <div className="presets" aria-label="Example trips">
        {PRESETS.map((p) => (
          <button
            key={p.name}
            type="button"
            className="preset"
            onClick={() => {
              setOrigin(p.origin)
              setDestination(p.destination)
            }}
          >
            {p.name}
          </button>
        ))}
      </div>

      <div className="places">
        <PlaceInput label="Origin" marker="A" placeholder="City, address or place" value={origin} onChange={setOrigin} />
        <button
          type="button"
          className="swap"
          title="Swap origin and destination"
          aria-label="Swap origin and destination"
          onClick={() => {
            setOrigin(destination)
            setDestination(origin)
          }}
        >
          ⇅
        </button>
        <PlaceInput
          label="Destination"
          marker="B"
          placeholder="City, address or place"
          value={destination}
          onChange={setDestination}
        />
      </div>
      {touched && (!origin || !destination) && <p className="field-error">Pick both places from the suggestions.</p>}

      <div className="row">
        <div className="field">
          <label htmlFor="departure">
            Departure <span className="muted">({localZone()})</span>
          </label>
          <input
            id="departure"
            type="datetime-local"
            value={departure}
            min={toLocalInput(now)}
            max={toLocalInput(maxDate)}
            onChange={(e) => setDeparture(e.target.value)}
            required
          />
        </div>
        <div className="field">
          <label htmlFor="load">Load weight (lb)</label>
          <input
            id="load"
            type="number"
            inputMode="numeric"
            min={0}
            max={200000}
            step={500}
            value={load}
            onChange={(e) => setLoad(e.target.value)}
            aria-invalid={touched && !loadValid}
          />
          <div className="chips" role="group" aria-label="Common loads">
            {LOAD_PRESETS.map((p) => (
              <button
                type="button"
                key={p.label}
                className={`chip-btn${loadNum === p.lbs ? ' on' : ''}`}
                onClick={() => setLoad(String(p.lbs))}
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>
      </div>
      {touched && !loadValid && <p className="field-error">Load must be between 0 and 200,000 lb.</p>}

      <div className="row row-center">
        <div className="field">
          <span className="label" id="interval-label">
            Weather every
          </span>
          <div className="segmented" role="radiogroup" aria-labelledby="interval-label">
            {([10, 25, 50] as const).map((mi) => (
              <button
                key={mi}
                type="button"
                role="radio"
                aria-checked={interval === mi}
                className={interval === mi ? 'on' : ''}
                onClick={() => setIntervalMi(mi)}
              >
                {mi} mi
              </button>
            ))}
          </div>
        </div>
        <label className="toggle" title="FMCSA Hours of Service: 30-min break after 8 h driving, 10-h rest after 11 h">
          <input type="checkbox" checked={hos} onChange={(e) => setHos(e.target.checked)} />
          <span className="toggle-track" aria-hidden />
          <span>HOS breaks</span>
        </label>
      </div>

      <button className="primary" type="submit" disabled={loading}>
        {loading ? (
          <>
            <span className="spinner" aria-hidden /> Checking routes & forecasts…
          </>
        ) : (
          'Find safest route'
        )}
      </button>
    </form>
  )
}
