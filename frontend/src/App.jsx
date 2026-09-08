import { useEffect, useState } from "react"

import "./App.css"
import {
  loadDarkModePreference,
  saveDarkModePreference,
} from "./theme.js"


const INITIAL_SYSTEM_STATUS = {
  system: "unknown",
  producer: "unknown",
  rabbitmq: "unknown",
  worker: "unknown",
  feature_store: "unknown",
  queue_depth: 0,
  worker_consumers: 0,
}

const INITIAL_PRODUCER_CONTROL = {
  running: false,
  pid: null,
}

const SERVICES = [
  {
    name: "Jenkins",
    port: 8082,
    icon: "/service-icons/jenkins.svg",
    description: "CI/CD pipelines",
  },
  {
    name: "Grafana",
    port: 3000,
    icon: "/service-icons/grafana.svg",
    description: "Dashboards and observability",
  },
  {
    name: "Prometheus",
    port: 9090,
    icon: "/service-icons/prometheus.svg",
    description: "Metrics and PromQL",
  },
  {
    name: "Jaeger",
    port: 16686,
    icon: "/service-icons/jaeger.svg",
    description: "Distributed tracing",
  },
  {
    name: "RabbitMQ",
    port: 15672,
    icon: "/service-icons/rabbitmq.svg",
    description: "Message broker management",
  },
  {
    name: "ClearML",
    port: 8080,
    icon: "/service-icons/clearml.svg",
    description: "Experiments and model management",
  },
]


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


function getServiceUrl(port) {
  const currentUrl = new URL(window.location.href)

  if (currentUrl.hostname.startsWith("5173-")) {
    currentUrl.hostname = currentUrl.hostname.replace(
      /^5173-/,
      `${port}-`
    )

    currentUrl.port = ""
    currentUrl.pathname = "/"
    currentUrl.search = ""
    currentUrl.hash = ""

    return currentUrl.toString()
  }

  return `http://localhost:${port}`
}


function App() {
  const [events, setEvents] = useState([])
  const [modelFilter, setModelFilter] = useState("all")
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const [systemStatus, setSystemStatus] = useState(
    INITIAL_SYSTEM_STATUS
  )
  const [statusError, setStatusError] = useState(false)

  const [producerControl, setProducerControl] = useState(
    INITIAL_PRODUCER_CONTROL
  )
  const [producerAction, setProducerAction] = useState(null)
  const [
    producerControlError,
    setProducerControlError,
  ] = useState(null)

  const [theme, setTheme] = useState(
    () => (
      loadDarkModePreference()
        ? "dark"
        : "light"
    )
  )

  const [servicesOpen, setServicesOpen] = useState(false)

  useEffect(() => {
    let isActive = true

    async function loadEvents() {
      try {
        const response = await fetch(
          "/api/events?limit=100"
        )

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

  useEffect(() => {
    let isActive = true

    async function loadProducerControl() {
      try {
        const response = await fetch(
          "/api/producer/status"
        )

        if (!response.ok) {
          throw new Error(
            `Failed to load Producer status: HTTP ${response.status}`
          )
        }

        const data = await response.json()

        if (isActive) {
          setProducerControl(data)
          setProducerControlError(null)
        }
      } catch (requestError) {
        if (isActive) {
          setProducerControlError(
            requestError.message
          )
        }
      }
    }

    loadProducerControl()

    const intervalId = window.setInterval(
      loadProducerControl,
      2000
    )

    return () => {
      isActive = false
      window.clearInterval(intervalId)
    }
  }, [])

  async function controlProducer(action) {
    setProducerAction(action)
    setProducerControlError(null)

    try {
      const response = await fetch(
        `/api/producer/${action}`,
        {
          method: "POST",
        }
      )

      if (!response.ok) {
        const errorData = await response.json()

        throw new Error(
          errorData.detail
          ?? `Producer ${action} failed: HTTP ${response.status}`
        )
      }

      const data = await response.json()

      setProducerControl(data)
    } catch (requestError) {
      setProducerControlError(
        requestError.message
      )
    } finally {
      setProducerAction(null)
    }
  }

  function toggleTheme() {
    const nextTheme = (
      theme === "light"
        ? "dark"
        : "light"
    )

    setTheme(nextTheme)

    saveDarkModePreference(
      nextTheme === "dark"
    )
  }

  const displayedSystemStatus = (
    statusError
      ? "unknown"
      : systemStatus.system
  )

  const producerActionName = (
    producerControl.running
      ? "stop"
      : "start"
  )

  let producerButtonText = (
    producerControl.running
      ? "Stop"
      : "Start"
  )

  let producerButtonIcon = (
    producerControl.running
      ? "■"
      : "▶"
  )

  if (producerAction === "start") {
    producerButtonText = "Starting..."
    producerButtonIcon = "…"
  }

  if (producerAction === "stop") {
    producerButtonText = "Stopping..."
    producerButtonIcon = "…"
  }

  const filteredEvents = (
    modelFilter === "all"
      ? events
      : events.filter(
        (event) => (
          event.inference_model_version
          === modelFilter
        )
      )
  )

  return (
    <div
      className={
        `app ${
          theme === "dark"
            ? "dark-mode"
            : ""
        }`
      }
    >
      <header className="topbar">
        <div className="topbar-title">
          <p className="eyebrow">
            MLOps Sentinel
          </p>

          <h1>
            Processing Monitor
          </h1>

          <p className="subtitle">
            Live visibility into the Sentinel ingestion pipeline
          </p>
        </div>

        <div className="topbar-actions">
          <div className="action-bar">
            <select
              className="toolbar-button"
              value={modelFilter}
              onChange={
                (event) => (
                  setModelFilter(
                    event.target.value
                  )
                )
              }
              aria-label="Filter by inference model"
            >
              <option value="all">
                Models: All
              </option>

              <option value="v1">
                Models: v1
              </option>

              <option value="v2">
                Models: v2
              </option>
            </select>

            <button
              className="toolbar-button services-button"
              type="button"
              onClick={
                () => setServicesOpen(true)
              }
            >
              <span
                className="toolbar-button-icon"
                aria-hidden="true"
              >
                ◫
              </span>

              <span>
                Services
              </span>
            </button>

            <a
              className="toolbar-button labeling-button"
              href="/labeling"
            >
              <span
                className="toolbar-button-icon"
                aria-hidden="true"
              >
                ✓
              </span>

              <span>
                Labeling
              </span>
            </a>

            <button
              className="toolbar-button theme-button"
              type="button"
              onClick={toggleTheme}
              title={
                theme === "light"
                  ? "Switch to dark mode"
                  : "Switch to light mode"
              }
              aria-label={
                theme === "light"
                  ? "Switch to dark mode"
                  : "Switch to light mode"
              }
            >
              <span
                className="theme-icon"
                aria-hidden="true"
              >
                {theme === "light" ? "☀" : "☾"}
              </span>
            </button>

            <button
              className={
                `toolbar-button ${
                  producerControl.running
                    ? "producer-stop-mode"
                    : "producer-start-mode"
                }`
              }
              type="button"
              disabled={
                producerAction !== null
              }
              onClick={
                () => controlProducer(
                  producerActionName
                )
              }
            >
              <span
                className="toolbar-button-icon"
                aria-hidden="true"
              >
                {producerButtonIcon}
              </span>

              <span>
                {producerButtonText}
              </span>
            </button>
          </div>

          <div className="system-status">
            <span
              className={
                `status-dot ${getStatusClass(
                  displayedSystemStatus
                )}`
              }
            />

            {statusError
              ? "Status Unavailable"
              : `System ${formatStatus(
                systemStatus.system
              )}`}
          </div>
        </div>
      </header>

      {servicesOpen && (
        <div
          className="modal-backdrop"
          role="presentation"
          onMouseDown={
            () => setServicesOpen(false)
          }
        >
          <div
            className="services-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="services-title"
            onMouseDown={
              (event) => (
                event.stopPropagation()
              )
            }
          >
            <div className="services-modal-header">
              <div>
                <h2 id="services-title">
                  Services
                </h2>

                <p>
                  Open Sentinel platform services
                </p>
              </div>

              <button
                className="modal-close-button"
                type="button"
                onClick={
                  () => setServicesOpen(false)
                }
                aria-label="Close services"
              >
                ×
              </button>
            </div>

            <div className="services-grid">
              {SERVICES.map((service) => (
                <a
                  className="service-card"
                  key={service.name}
                  href={
                    getServiceUrl(
                      service.port
                    )
                  }
                  target="_blank"
                  rel="noreferrer"
                >
                  <span className="service-logo">
                    <img
                      src={service.icon}
                      alt=""
                      aria-hidden="true"
                    />
                  </span>

                  <span className="service-details">
                    <strong>
                      {service.name}
                    </strong>

                    <small>
                      {service.description}
                    </small>
                  </span>

                  <span
                    className="service-open-icon"
                    aria-hidden="true"
                  >
                    ↗
                  </span>
                </a>
              ))}
            </div>
          </div>
        </div>
      )}

      {producerControlError && (
        <div className="topbar-control-error">
          {producerControlError}
        </div>
      )}

      <main>
        <section className="pipeline-section">
          <h2>
            Pipeline
          </h2>

          <div className="pipeline">
            <div className="pipeline-node">
              <span
                className={
                  `node-status ${getStatusClass(
                    systemStatus.producer
                  )}`
                }
              />

              <div>
                <strong>
                  Producer
                </strong>

                <small>
                  {formatStatus(
                    systemStatus.producer
                  )}
                </small>
              </div>
            </div>

            <span className="arrow">
              →
            </span>

            <div className="pipeline-node">
              <span
                className={
                  `node-status ${getStatusClass(
                    systemStatus.rabbitmq
                  )}`
                }
              />

              <div>
                <strong>
                  RabbitMQ
                </strong>

                <small>
                  {formatStatus(
                    systemStatus.rabbitmq
                  )}
                  {" · "}
                  Queue {systemStatus.queue_depth}
                </small>
              </div>
            </div>

            <span className="arrow">
              →
            </span>

            <div className="pipeline-node">
              <span
                className={
                  `node-status ${getStatusClass(
                    systemStatus.worker
                  )}`
                }
              />

              <div>
                <strong>
                  Worker
                </strong>

                <small>
                  {formatStatus(
                    systemStatus.worker
                  )}
                  {" · "}
                  Consumers {
                    systemStatus.worker_consumers
                  }
                </small>
              </div>
            </div>

            <span className="arrow">
              →
            </span>

            <div className="pipeline-node">
              <span
                className={
                  `node-status ${getStatusClass(
                    systemStatus.feature_store
                  )}`
                }
              />

              <div>
                <strong>
                  Feature Store
                </strong>

                <small>
                  {formatStatus(
                    systemStatus.feature_store
                  )}
                </small>
              </div>
            </div>
          </div>
        </section>

        <section className="events-section">
          <div className="section-heading">
            <div>
              <h2>
                Processed Images
              </h2>

              <p>
                Latest images successfully processed by the Worker
              </p>
            </div>

            <span className="event-count">
              {filteredEvents.length} events
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
                    <th>Inference Model</th>
                    <th>Prediction</th>
                    <th>Confidence</th>
                    <th>Label</th>
                    <th>Status</th>
                  </tr>
                </thead>

                <tbody>
                  {filteredEvents.map(
                    (event) => (
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
                          {formatTimestamp(
                            event.timestamp
                          )}
                        </td>

                        <td>
                          {
                            event.inference_model_version
                              ? (
                                <span className="model-badge">
                                  {
                                    event.inference_model_version
                                  }
                                </span>
                              )
                              : (
                                <span className="muted">
                                  —
                                </span>
                              )
                          }
                        </td>

                        <td>
                          {
                            event.predicted_class
                            ?? (
                              <span className="muted">
                                —
                              </span>
                            )
                          }
                        </td>

                        <td>
                          {
                            event.confidence != null
                              ? (
                                `${(
                                  event.confidence
                                  * 100
                                ).toFixed(1)}%`
                              )
                              : (
                                <span className="muted">
                                  —
                                </span>
                              )
                          }
                        </td>

                        <td>
                          {
                            event.label
                            ?? (
                              <span className="unlabeled">
                                Unlabeled
                              </span>
                            )
                          }
                        </td>

                        <td>
                          <span className="processed-status">
                            <span
                              className={
                                "status-dot status-healthy"
                              }
                            />

                            {event.status}
                          </span>
                        </td>
                      </tr>
                    )
                  )}
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