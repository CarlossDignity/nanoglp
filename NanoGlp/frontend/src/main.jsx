import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App.jsx'
import { AuthProvider } from './state/AuthContext.jsx'
import { PreferencesProvider } from './state/PreferencesContext.jsx'
import { MockStoreProvider } from './state/MockStore.jsx'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <PreferencesProvider>
        <AuthProvider>
          <MockStoreProvider>
            <App />
          </MockStoreProvider>
        </AuthProvider>
      </PreferencesProvider>
    </BrowserRouter>
  </React.StrictMode>,
)
