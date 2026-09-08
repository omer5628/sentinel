import { StrictMode } from "react"
import { createRoot } from "react-dom/client"

import "./index.css"
import App from "./App.jsx"
import LabelingPage from "./LabelingPage.jsx"


const normalizedPath = (
  window.location.pathname.replace(/\/+$/, "")
  || "/"
)

const page = (
  normalizedPath === "/labeling"
    ? <LabelingPage />
    : <App />
)


createRoot(
  document.getElementById("root")
).render(
  <StrictMode>
    {page}
  </StrictMode>,
)