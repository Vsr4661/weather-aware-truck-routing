import { useEffect, useId, useRef, useState } from 'react'
import { geocode } from '../api'
import type { Place } from '../types'

interface Props {
  label: string
  placeholder: string
  value: Place | null
  onChange: (place: Place | null) => void
  marker: 'A' | 'B'
}

export default function PlaceInput({ label, placeholder, value, onChange, marker }: Props) {
  const id = useId()
  const [text, setText] = useState(value?.label ?? '')
  const [results, setResults] = useState<Place[]>([])
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const [loading, setLoading] = useState(false)
  const typed = useRef(false)

  // Reflect external changes (presets, swap) in the text box.
  useEffect(() => {
    typed.current = false
    setText(value?.label ?? '')
  }, [value])

  useEffect(() => {
    if (!typed.current || text.trim().length < 2) {
      setResults([])
      return
    }
    const ctrl = new AbortController()
    const timer = window.setTimeout(async () => {
      setLoading(true)
      try {
        const { results } = await geocode(text, ctrl.signal)
        setResults(results)
        setActive(0)
        setOpen(true)
      } catch {
        if (!ctrl.signal.aborted) setResults([])
      } finally {
        if (!ctrl.signal.aborted) setLoading(false)
      }
    }, 250)
    return () => {
      ctrl.abort()
      window.clearTimeout(timer)
    }
  }, [text])

  const pick = (place: Place) => {
    onChange(place)
    setOpen(false)
  }

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (!open || !results.length) return
    if (e.key === 'ArrowDown') setActive((a) => (a + 1) % results.length)
    else if (e.key === 'ArrowUp') setActive((a) => (a - 1 + results.length) % results.length)
    else if (e.key === 'Enter') pick(results[active])
    else if (e.key === 'Escape') setOpen(false)
    else return
    e.preventDefault()
  }

  return (
    <div className="field place">
      <label htmlFor={id}>{label}</label>
      <div className="place-box">
        <span className={`place-dot place-dot-${marker}`} aria-hidden>
          {marker}
        </span>
        <input
          id={id}
          role="combobox"
          aria-expanded={open}
          aria-controls={`${id}-list`}
          aria-autocomplete="list"
          autoComplete="off"
          placeholder={placeholder}
          value={text}
          onChange={(e) => {
            typed.current = true
            setText(e.target.value)
            if (value) onChange(null)
          }}
          onFocus={() => results.length && setOpen(true)}
          onBlur={() => window.setTimeout(() => setOpen(false), 150)}
          onKeyDown={onKeyDown}
        />
        {loading && <span className="spinner small" aria-label="Searching" />}
      </div>
      {open && results.length > 0 && (
        <ul className="suggestions" id={`${id}-list`} role="listbox">
          {results.map((r, i) => (
            <li
              key={`${r.label}-${i}`}
              role="option"
              aria-selected={i === active}
              className={i === active ? 'active' : ''}
              onMouseDown={(e) => {
                e.preventDefault()
                pick(r)
              }}
              onMouseEnter={() => setActive(i)}
            >
              {r.label}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
