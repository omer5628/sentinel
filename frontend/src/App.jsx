import { useEffect, useState } from "react"

import "./App.css"


const INITIAL_SYSTEM_STATUS = {
  system: "unknown",
  producer: "unknown",
  rabbitmq: "unknown",
  worker: "unknown",
  feature_store: "unknown",
  queue_depth: 0,
  worker_consumers: 0,
}


function formatTimestamp(timestamp) {
  return new Date(timestamp).toLocaleString()
}


function formatStatus(status) {
  return status.charAt(0).toUpperCase() + status.slice(1)
}


function getStatusClass(status) {
  if (status === "online" || status === "active") {
    return "status-healthy"
  }

  if (status === "idle") {
    return "status-idle"
  }

  if (status === "offline" || status === "degraded") {
    return "status-error"
  }

  return "status-unknown"
}


function App() {
  const [events, setEvents] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const [systemStatus, setSystemStatus] = useState(
    INITIAL_SYSTEM_STATUS
  )
  const [statusError, setStatusError] = useState(false)

  useEffect(() => {
    let isActive = true

    async function loadEvents() {
      try {
        const response = await fetch("/api/events?limit=100")

        if (!response.ok) {
          throw new Error(
            `Failed to load events: HTTP ${response.status}`
          )
        }

        const data = await response.json()

        if (isActive) {
          setEvents(data)
          setError(null)
        }
      } catch (requestError) {
        if (isActive) {
          setError(requestError.message)
        }
      } finally {
        if (isActive) {
          setLoading(false)
        }
      }
    }

    loadEvents()

    const intervalId = window.setInterval(
      loadEvents,
      2000
    )

    return () => {
      isActive = false
      window.clearInterval(intervalId)
    }
  }, [])

  useEffect(() => {
    let isActive = true

    async function loadSystemStatus() {
      try {
        const response = await fetch("/api/status")

        if (!response.ok) {
          throw new Error(
            `Failed to load status: HTTP ${response.status}`
          )
        }

        const data = await response.json()

        if (isActive) {
          setSystemStatus(data)
          setStatusError(false)
        }
      } catch {
        if (isActive) {
          setStatusError(true)
        }
      }
    }

    loadSystemStatus()

    const intervalId = window.setInterval(
      loadSystemStatus,
      2000
    )

    return () => {
      isActive = false
      window.clearInterval(intervalId)
    }
  }, [])

  const displayedSystemStatus = statusError
    ? "unknown"
    : systemStatus.system

  return (
    <div className="app">
      <header className="topbar">
        <div>
          <p className="eyebrow">MLOps Sentinel</p>
          <h1>Processing Monitor</h1>
          <p className="subtitle">
            Live visibility into the Sentinel ingestion pipeline
          </p>
        </div>

        <div className="system-status">
          <span
            className={
              `status-dot ${getStatusClass(displayedSystemStatus)}`
            }
          />
          {statusError
            ? "Status Unavailable"
            : `System ${formatStatus(systemStatus.system)}`}
        </div>
      </header>

      <main>
        <section className="pipeline-section">
          <h2>Pipeline</h2>

          <div className="pipeline">
            <div className="pipeline-node">
              <span
                className={
                  `node-status ${getStatusClass(systemStatus.producer)}`
                }
              />
              <div>
                <strong>Producer</strong>
                <small>
                  {formatStatus(systemStatus.producer)}
                </small>
              </div>
            </div>

            <span className="arrow">→</span>

            <div className="pipeline-node">
              <span
                className={
                  `node-status ${getStatusClass(systemStatus.rabbitmq)}`
                }
              />
              <div>
                <strong>RabbitMQ</strong>
                <small>
                  {formatStatus(systemStatus.rabbitmq)}
                  {" · "}
                  Queue {systemStatus.queue_depth}
                </small>
              </div>
            </div>

            <span className="arrow">→</span>

            <div className="pipeline-node">
              <span
                className={
                  `node-status ${getStatusClass(systemStatus.worker)}`
                }
              />
              <div>
                <strong>Worker</strong>
                <small>
                  {formatStatus(systemStatus.worker)}
                  {" · "}
                  Consumers {systemStatus.worker_consumers}
                </small>
              </div>
            </div>

            <span className="arrow">→</span>

            <div className="pipeline-node">
              <span
                className={
                  `node-status ${getStatusClass(
                    systemStatus.feature_store
                  )}`
                }
              />
              <div>
                <strong>Feature Store</strong>
                <small>
                  {formatStatus(systemStatus.feature_store)}
                </small>
              </div>
            </div>
          </div>
        </section>

        <section className="events-section">
          <div className="section-heading">
            <div>
              <h2>Processed Images</h2>
              <p>
                Latest images successfully processed by the Worker
              </p>
            </div>

            <span className="event-count">
              {events.length} events
            </span>
          </div>

          {loading && (
            <div className="message-box">
              Loading processed images...
            </div>
          )}

          {error && (
            <div className="message-box error-message">
              {error}
            </div>
          )}

          {!loading && !error && (
            <div className="table-wrapper">
              <table>
                <thead>
                  <tr>
                    <th>Image</th>
                    <th>Image ID</th>
                    <th>Event ID</th>
                    <th>Timestamp</th>
                    <th>Model</th>
                    <th>Label</th>
                    <th>Status</th>
                  </tr>
                </thead>

                <tbody>
                  {events.map((event) => (
                    <tr key={event.event_id}>
                      <td>
                        <img
                          className="real-image-preview"
                          src={
                            `/api/events/${event.event_id}/image`
                          }
                          alt={
                            `Processed image ${event.image_id}`
                          }
                        />
                      </td>

                      <td className="mono">
                        {event.image_id}
                      </td>

                      <td
                        className="mono muted"
                        title={event.event_id}
                      >
                        {event.event_id}
                      </td>

                      <td>
                        {formatTimestamp(event.timestamp)}
                      </td>

                      <td>
                        <span className="model-badge">
                          {event.model_version}
                        </span>
                      </td>

                      <td>
                        {event.label ?? (
                          <span className="unlabeled">
                            Unlabeled
                          </span>
                        )}
                      </td>

                      <td>
                        <span className="processed-status">
                          <span
                            className="status-dot status-healthy"
                          />
                          {event.status}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </main>
    </div>
  )
}

export default App