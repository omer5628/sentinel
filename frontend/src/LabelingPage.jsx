import { useEffect, useState } from "react"

import "./LabelingPage.css"
import {
  loadDarkModePreference,
  saveDarkModePreference,
} from "./theme.js"


const LABELS = [
  "0",
  "1",
  "2",
  "3",
  "4",
  "5",
  "6",
  "7",
  "8",
  "9",
]


async function requestLabelingStats() {
  const response = await fetch("/api/labeling/stats")

  if (!response.ok) {
    throw new Error(
      `Failed to load labeling stats: HTTP ${response.status}`
    )
  }

  return response.json()
}


async function requestNextLabelingEvent() {
  const response = await fetch("/api/labeling/next")

  if (response.status === 404) {
    return null
  }

  if (!response.ok) {
    throw new Error(
      `Failed to load labeling event: HTTP ${response.status}`
    )
  }

  return response.json()
}


function LabelingPage() {
  const [labelingEvent, setLabelingEvent] = useState(null)

  const [stats, setStats] = useState({
    labeled: 0,
    unlabeled: 0,
    total: 0,
  })

  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)
  const [completed, setCompleted] = useState(false)

  const [darkMode, setDarkMode] = useState(
    loadDarkModePreference
  )

  useEffect(() => {
    let isActive = true

    Promise.all([
      requestLabelingStats(),
      requestNextLabelingEvent(),
    ])
      .then(([statsData, eventData]) => {
        if (!isActive) {
          return
        }

        setStats(statsData)
        setLabelingEvent(eventData)
        setCompleted(eventData === null)
        setError(null)
      })
      .catch((requestError) => {
        if (!isActive) {
          return
        }

        setError(requestError.message)
      })
      .finally(() => {
        if (!isActive) {
          return
        }

        setLoading(false)
      })

    return () => {
      isActive = false
    }
  }, [])

  function toggleDarkMode() {
    const nextDarkMode = !darkMode

    setDarkMode(nextDarkMode)
    saveDarkModePreference(nextDarkMode)
  }

  async function submitLabel(label) {
    if (!labelingEvent || submitting) {
      return
    }

    setSubmitting(true)
    setError(null)

    try {
      const response = await fetch(
        `/api/events/${labelingEvent.event_id}/label`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            label,
          }),
        }
      )

      if (!response.ok) {
        let detail = `HTTP ${response.status}`

        try {
          const responseBody = await response.json()
          detail = responseBody.detail ?? detail
        } catch {
          // Keep the HTTP status fallback.
        }

        throw new Error(
          `Failed to save label: ${detail}`
        )
      }

      const [
        statsData,
        eventData,
      ] = await Promise.all([
        requestLabelingStats(),
        requestNextLabelingEvent(),
      ])

      setStats(statsData)
      setLabelingEvent(eventData)
      setCompleted(eventData === null)
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setSubmitting(false)
    }
  }

  const progressPercentage = (
    stats.total === 0
      ? 0
      : (stats.labeled / stats.total) * 100
  )

  return (
    <div
      className={
        `labeling-app ${darkMode ? "dark-mode" : ""}`
      }
    >
      <header className="labeling-topbar">
        <div>
          <p className="labeling-eyebrow">
            MLOps Sentinel
          </p>

          <h1>
            Human Labeling
          </h1>

          <p className="labeling-subtitle">
            Create ground truth for processed MNIST images
          </p>
        </div>

        <div className="labeling-topbar-actions">
          <button
            className="labeling-theme-button"
            type="button"
            onClick={toggleDarkMode}
            aria-label={
              darkMode
                ? "Switch to light mode"
                : "Switch to dark mode"
            }
            title={
              darkMode
                ? "Light mode"
                : "Dark mode"
            }
          >
            <span aria-hidden="true">
              {darkMode ? "☀" : "☾"}
            </span>
          </button>

          <a
            className="monitor-link"
            href="/"
          >
            ← Processing Monitor
          </a>
        </div>
      </header>

      <main className="labeling-main">
        <section className="labeling-stats-card">
          <div className="labeling-stats-heading">
            <div>
              <h2>
                Labeling Progress
              </h2>

              <p>
                Human-reviewed samples in the offline feature store
              </p>
            </div>

            <strong className="labeling-progress-value">
              {progressPercentage.toFixed(1)}%
            </strong>
          </div>

          <div className="labeling-progress-track">
            <div
              className="labeling-progress-fill"
              style={{
                width: `${progressPercentage}%`,
              }}
            />
          </div>

          <div className="labeling-stat-grid">
            <div>
              <span>
                Labeled
              </span>

              <strong>
                {stats.labeled}
              </strong>
            </div>

            <div>
              <span>
                Unlabeled
              </span>

              <strong>
                {stats.unlabeled}
              </strong>
            </div>

            <div>
              <span>
                Total
              </span>

              <strong>
                {stats.total}
              </strong>
            </div>
          </div>
        </section>

        {loading && (
          <div className="labeling-message">
            Loading next image...
          </div>
        )}

        {error && (
          <div className="labeling-message labeling-error">
            {error}
          </div>
        )}

        {!loading && completed && !error && (
          <div className="labeling-message labeling-complete">
            All available images have been labeled.
          </div>
        )}

        {!loading && labelingEvent && !error && (
          <section className="labeling-workspace">
            <div className="labeling-image-panel">
              <div className="labeling-panel-heading">
                <div>
                  <h2>
                    Image
                  </h2>

                  <p>
                    Inspect the image before choosing its ground-truth label
                  </p>
                </div>

                <span className="unlabeled-badge">
                  Unlabeled
                </span>
              </div>

              <div className="labeling-image-frame">
                <img
                  src={
                    `/api/events/${labelingEvent.event_id}/image`
                  }
                  alt={
                    `MNIST image ${labelingEvent.image_id}`
                  }
                />
              </div>

              <div className="labeling-image-metadata">
                <div>
                  <span>
                    Image ID
                  </span>

                  <code>
                    {labelingEvent.image_id}
                  </code>
                </div>

                <div>
                  <span>
                    Event ID
                  </span>

                  <code>
                    {labelingEvent.event_id}
                  </code>
                </div>
              </div>
            </div>

            <div className="labeling-control-panel">
              <div>
                <h2>
                  Choose Ground Truth
                </h2>

                <p className="labeling-instructions">
                  Select the digit that is actually visible in the image.
                </p>
              </div>

              <div className="label-grid">
                {LABELS.map((label) => (
                  <button
                    className="label-button"
                    key={label}
                    type="button"
                    disabled={submitting}
                    onClick={() => submitLabel(label)}
                  >
                    {label}
                  </button>
                ))}
              </div>

              <button
                className="discard-button"
                type="button"
                disabled={submitting}
                onClick={() => submitLabel("Discard")}
              >
                Discard image
              </button>

              {submitting && (
                <p className="saving-label-message">
                  Saving label...
                </p>
              )}

              <div className="blind-labeling-note">
                <strong>
                  Blind labeling
                </strong>

                <p>
                  Model prediction and confidence are intentionally hidden
                  while labeling to avoid influencing the human ground truth.
                </p>
              </div>
            </div>
          </section>
        )}
      </main>
    </div>
  )
}


export default LabelingPage