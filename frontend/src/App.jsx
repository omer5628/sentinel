import { useEffect, useState } from "react"

import "./App.css"


function formatTimestamp(timestamp) {
  return new Date(timestamp).toLocaleString()
}


function App() {
  const [events, setEvents] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    async function loadEvents() {
      try {
        const response = await fetch("/api/events?limit=100")

        if (!response.ok) {
          throw new Error(
            `Failed to load events: HTTP ${response.status}`
          )
        }

        const data = await response.json()

        setEvents(data)
        setError(null)
      } catch (requestError) {
        setError(requestError.message)
      } finally {
        setLoading(false)
      }
    }

    loadEvents()
  }, [])

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
          <span className="status-dot" />
          System Online
        </div>
      </header>

      <main>
        <section className="pipeline-section">
          <h2>Pipeline</h2>

          <div className="pipeline">
            <div className="pipeline-node">
              <span className="node-status" />
              <div>
                <strong>Producer</strong>
                <small>Publishing images</small>
              </div>
            </div>

            <span className="arrow">→</span>

            <div className="pipeline-node">
              <span className="node-status" />
              <div>
                <strong>RabbitMQ</strong>
                <small>video_stream</small>
              </div>
            </div>

            <span className="arrow">→</span>

            <div className="pipeline-node">
              <span className="node-status" />
              <div>
                <strong>Worker</strong>
                <small>Processing events</small>
              </div>
            </div>

            <span className="arrow">→</span>

            <div className="pipeline-node">
              <span className="node-status" />
              <div>
                <strong>Feature Store</strong>
                <small>Redis / PostgreSQL</small>
              </div>
            </div>
          </div>
        </section>

        <section className="events-section">
          <div className="section-heading">
            <div>
              <h2>Processed Images</h2>
              <p>Latest images successfully processed by the Worker</p>
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
                          src={`/api/events/${event.event_id}/image`}
                          alt={`Processed image ${event.image_id}`}
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
                          <span className="status-dot" />
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