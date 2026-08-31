import { useEffect, useRef, useState } from 'react'

const API_URL = import.meta.env.VITE_AI_API_URL || '/api/buyer'
const PROFILE_STORAGE_KEY = 'ai-buyer-profile'
const initialPreferences = {
  product_request: '', budget: '2000', quantity: '1', customer_name: '',
  customer_email: '', shipping_address: '', payment_method: 'card',
}

const buildRequestPayload = (preferences, request) => {
  const payload = {
    product_request: request,
    budget: Number(preferences.budget),
    quantity: Number(preferences.quantity),
    payment_method: preferences.payment_method || 'card',
  }

  if (preferences.customer_name) payload.customer_name = preferences.customer_name
  if (preferences.customer_email) payload.customer_email = preferences.customer_email
  if (preferences.shipping_address) payload.shipping_address = preferences.shipping_address

  return payload
}

const parsePurchaseSummary = (data, fallbackPreferences = {}) => {
  const message = typeof data?.message === 'string' ? data.message.trim() : ''
  const error = typeof data?.error === 'string' ? data.error.trim() : ''
  const source = data?.summary ?? data ?? {}
  const auditEntries = Array.isArray(data?.audit) ? data.audit : []
  let auditDetail = {}

  for (const entry of auditEntries) {
    if (!entry || typeof entry !== 'object') continue
    const event = entry.event
    const payload = entry.payload || entry.data || {}
    if (event === 'purchase') {
      auditDetail = { ...auditDetail, ...payload }
    }
    if (event === 'payment_attempt') {
      auditDetail = { ...auditDetail, ...payload }
    }
  }

  const summarySource = { ...source, ...auditDetail }
  const fallbackProduct = summarySource.product || summarySource.product_name || summarySource.item || ''
  const product = fallbackProduct || (() => {
    const match = message.match(/(?:product|item|purchase)[:\-]?\s*([A-Za-z0-9 &/().,-]+)/i)
    return match ? match[1].trim() : ''
  })()
  const total = summarySource.total ?? summarySource.amount ?? (() => {
    const match = message.match(/(?:total|amount)[:\-]?\s*\$?([0-9][0-9,\.\d]*)/i)
    return match ? Number(match[1].replace(/,/g, '')) : null
  })()
  const orderId = summarySource.order_id ?? summarySource.orderId ?? (() => {
    const match = message.match(/(?:order(?:\s+id)?|order)[:\-]?\s*#?([0-9]+)/i)
    return match ? Number(match[1]) : null
  })()
  const paymentStatus = summarySource.payment_status ?? summarySource.paymentStatus ?? (() => {
    const match = message.match(/payment\s+status[:\-]?\s*([A-Za-z]+)/i)
    return match ? match[1].trim() : ''
  })()
  const orderStatus = summarySource.status ?? summarySource.order_status ?? summarySource.orderStatus ?? (() => {
    const match = message.match(/order\s+status[:\-]?\s*([A-Za-z]+)/i)
    return match ? match[1].trim() : ''
  })()

  return {
    message,
    error,
    product: product || fallbackPreferences.product_request || '',
    total,
    order_id: orderId,
    payment_status: paymentStatus || (summarySource.payment_status ? String(summarySource.payment_status) : ''),
    status: orderStatus || (summarySource.status ? String(summarySource.status) : ''),
    customer_name: summarySource.customer_name || summarySource.customerName || fallbackPreferences.customer_name || '',
    customer_email: summarySource.customer_email || summarySource.customerEmail || fallbackPreferences.customer_email || '',
    shipping_address: summarySource.shipping_address || summarySource.shippingAddress || fallbackPreferences.shipping_address || '',
  }
}

function AgentMark() {
  return <span className="agent-mark" aria-hidden="true">✦</span>
}

function App() {
  const storedProfile = (() => {
    try {
      const saved = localStorage.getItem(PROFILE_STORAGE_KEY)
      return saved ? JSON.parse(saved) : null
    } catch {
      return null
    }
  })()

  const [messages, setMessages] = useState([{ id: 1, type: 'agent', text: "Hello. I'm ready to help you find and buy the right product. What are you looking for?" }])
  const [draft, setDraft] = useState('')
  const [preferences, setPreferences] = useState({ ...initialPreferences, ...(storedProfile || {}) })
  const [isRunning, setIsRunning] = useState(false)
  const [audit, setAudit] = useState([])
  const [result, setResult] = useState(null)
  const [fileName, setFileName] = useState('')
  const [isLoggedIn, setIsLoggedIn] = useState(Boolean(storedProfile?.customer_name || storedProfile?.customer_email || storedProfile?.shipping_address))
  const [loginForm, setLoginForm] = useState({
    customer_name: storedProfile?.customer_name || '',
    customer_email: storedProfile?.customer_email || '',
    shipping_address: storedProfile?.shipping_address || '',
    payment_method: storedProfile?.payment_method || 'card',
  })
  const fileInput = useRef(null)
  const purchaseSummary = parsePurchaseSummary(result, preferences)
  const workspaceStatus = isRunning ? 'Running' : result?.error ? 'Failed' : result ? 'Completed' : 'Recorded'

  useEffect(() => {
    if (!isLoggedIn) return
    localStorage.setItem(PROFILE_STORAGE_KEY, JSON.stringify({ ...preferences, ...loginForm }))
    setPreferences((current) => ({ ...current, ...loginForm }))
  }, [isLoggedIn, loginForm, preferences])

  const updatePreference = (key, value) => setPreferences((current) => ({ ...current, [key]: value }))

  const handleLogin = (event) => {
    event.preventDefault()
    const cleaned = {
      customer_name: loginForm.customer_name.trim(),
      customer_email: loginForm.customer_email.trim(),
      shipping_address: loginForm.shipping_address.trim(),
      payment_method: loginForm.payment_method || 'card',
    }

    if (!cleaned.customer_name || !cleaned.customer_email || !cleaned.shipping_address) {
      setMessages((current) => [...current, { id: Date.now(), type: 'agent', text: 'Please complete your name, email, and shipping address to continue.' }])
      return
    }

    setPreferences((current) => ({ ...current, ...cleaned }))
    localStorage.setItem(PROFILE_STORAGE_KEY, JSON.stringify(cleaned))
    setIsLoggedIn(true)
    setMessages((current) => [...current, { id: Date.now(), type: 'agent', text: `Welcome, ${cleaned.customer_name}. Your buyer details are ready.` }])
  }

  const handleLogout = () => {
    localStorage.removeItem(PROFILE_STORAGE_KEY)
    setIsLoggedIn(false)
    setPreferences({ ...initialPreferences, product_request: preferences.product_request, budget: preferences.budget, quantity: preferences.quantity, payment_method: 'card' })
    setLoginForm({ customer_name: '', customer_email: '', shipping_address: '', payment_method: 'card' })
  }

  const sendMessage = async (text = draft) => {
    const value = text.trim()
    if (!value || isRunning) return
    const currentProfile = { ...preferences, ...loginForm }
    const request = currentProfile.product_request || value
    updatePreference('product_request', request)
    setMessages((current) => [...current, { id: Date.now(), type: 'user', text: value }, { id: Date.now() + 1, type: 'agent', text: 'I am checking your taste, budget, and store inventory now.' }])
    setDraft('')
    setIsRunning(true)
    setResult(null)
    setAudit([])
    try {
      const response = await fetch(API_URL, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(buildRequestPayload(currentProfile, request)) })
      if (!response.ok || !response.body) {
        let detail = `Buyer service returned HTTP ${response.status}`
        try {
          const errorData = await response.json()
          detail = errorData.error || detail
        } catch {
          // Keep the HTTP error when the service does not return JSON.
        }
        throw new Error(detail)
      }
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let data = {}
      while (true) {
        const chunk = await reader.read()
        buffer += decoder.decode(chunk.value || new Uint8Array(), { stream: !chunk.done })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''
        for (const line of lines) {
          if (!line.trim()) continue
          const event = JSON.parse(line)
          if (event.type === 'audit') setAudit((current) => [...current, event.data])
          if (event.type === 'result') data = event.data
        }
        if (chunk.done) break
      }
      setResult(data)
      setMessages((current) => [...current, { id: Date.now(), type: 'agent', text: data.message || data.error || 'The buyer protocol could not complete.' }])
    } catch (error) {
      const detail = error instanceof Error ? error.message : 'Unable to reach the AI buyer service.'
      setResult({ error: detail })
      setMessages((current) => [...current, { id: Date.now(), type: 'agent', text: `${detail} Check that ai_api.py is running at ${API_URL}.` }])
    } finally {
      setIsRunning(false)
    }
  }

  const handleFile = (event) => {
    const file = event.target.files?.[0]
    if (!file) return
    setFileName(file.name)
    setAudit((current) => [...current, { event: 'attachment', detail: `${file.name} attached for buyer context`, timestamp: new Date().toISOString() }])
  }

  if (!isLoggedIn) {
    return (
      <main className="login-shell">
        <section className="login-card" aria-label="Buyer login">
          <div className="brand-lockup login-brand"><AgentMark /><span>AI Buyer</span></div>
          <h1>Sign in to continue</h1>
          <p>Set your profile once and let the agent use it for each purchase request.</p>
          <form className="login-form" onSubmit={handleLogin}>
            <label>
              Full name
              <input value={loginForm.customer_name} onChange={(event) => setLoginForm((current) => ({ ...current, customer_name: event.target.value }))} placeholder="Jane Smith" required />
            </label>
            <label>
              Email
              <input type="email" value={loginForm.customer_email} onChange={(event) => setLoginForm((current) => ({ ...current, customer_email: event.target.value }))} placeholder="jane@example.com" required />
            </label>
            <label>
              Shipping address
              <textarea value={loginForm.shipping_address} onChange={(event) => setLoginForm((current) => ({ ...current, shipping_address: event.target.value }))} placeholder="Your delivery address" rows="3" required />
            </label>
            <label>
              Payment method
              <select value={loginForm.payment_method} onChange={(event) => setLoginForm((current) => ({ ...current, payment_method: event.target.value }))}>
                <option value="card">Card</option>
                <option value="upi">UPI</option>
                <option value="wallet">Wallet</option>
                <option value="cod">Cash on Delivery</option>
              </select>
            </label>
            <button className="login-button" type="submit">Continue to buyer</button>
          </form>
        </section>
      </main>
    )
  }

  return (
    <main className="app-shell">
      <section className="chat-panel" aria-label="Agent conversation">
        <header className="panel-header">
          <div className="brand-lockup"><AgentMark /><span>Agent</span></div>
          <div className="header-actions">
            <button className="header-button" type="button" aria-label="Open agent options">•••</button>
            <button className="header-button logout-button" type="button" onClick={handleLogout}>Logout</button>
          </div>
        </header>
        <div className="conversation">
          {messages.map((message) => <article className={`message ${message.type}`} key={message.id}>{message.type === 'agent' && <AgentMark />}<div className="message-body">{message.type === 'agent' && <div className="message-author">Agent</div>}<p>{message.text}</p></div></article>)}
          {messages.length === 1 && <button className="suggestion" disabled={isRunning} type="button" onClick={() => sendMessage('Find a wireless gaming headset')}>Find a product that matches my preferences and budget.</button>}
        </div>
        <div className="composer-area">
          {fileName && <div className="attachment-chip">{fileName}<button type="button" onClick={() => setFileName('')} aria-label="Remove attachment">×</button></div>}
          <form className="composer" onSubmit={(event) => { event.preventDefault(); sendMessage() }}><textarea disabled={isRunning} value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); sendMessage() } }} placeholder={isRunning ? 'Buyer protocol running...' : 'Tell me what you want to buy...'} aria-label="Message" rows="1" /><button className="send-button" disabled={isRunning} type="submit" aria-label="Send message">{isRunning ? '…' : '➤'}</button></form>
          <div className="composer-tools"><button type="button" disabled={isRunning} onClick={() => fileInput.current?.click()} aria-label="Attach a file">⌕ <span>Attach</span></button><input ref={fileInput} type="file" onChange={handleFile} hidden /><button type="button" aria-label="Use voice input">♩</button></div>
        </div>
      </section>
      <section className="workspace-panel" aria-label="Workspace">
        <header className="workspace-header"><span>Workspace</span><button type="button" aria-label="Expand workspace">↗</button></header>
        <div className="workspace-content">
          {!audit.length && <><div className="workspace-icon" aria-hidden="true">⊞</div><h1>Buyer workspace</h1><p>Set your taste and budget, then the agent will check the store and audit each decision here.</p></>}
          <div className="buyer-brief"><div className="brief-heading"><span>Buyer brief</span><span className="budget-lock">Budget lock</span></div><label>What are you looking for?<input value={preferences.product_request} onChange={(event) => updatePreference('product_request', event.target.value)} placeholder="e.g. wireless gaming headset" disabled={isRunning} /></label><div className="brief-grid"><label>Budget<input type="number" min="1" value={preferences.budget} onChange={(event) => updatePreference('budget', event.target.value)} disabled={isRunning} /></label><label>Quantity<input type="number" min="1" value={preferences.quantity} onChange={(event) => updatePreference('quantity', event.target.value)} disabled={isRunning} /></label></div><label>Product taste / preferences<textarea value={preferences.product_request} onChange={(event) => updatePreference('product_request', event.target.value)} placeholder="Tell the buyer what matters to you" disabled={isRunning} rows="2" /></label></div>
          {audit.length > 0 && <div className="audit-panel"><div className="audit-heading"><span>Live audit</span><span className={isRunning ? 'pulse status-running' : result?.error ? 'status-failed' : 'status-done'}>{workspaceStatus}</span></div>{audit.map((item, index) => <div className="audit-item" key={`${item.timestamp}-${index}`}><span className="audit-dot" /><div><strong>{item.event.replaceAll('_', ' ')}</strong><p>{item.detail}</p></div><time>{new Date(item.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</time></div>)}</div>}
          {(result?.message || result?.error || purchaseSummary.product || purchaseSummary.order_id || purchaseSummary.total || purchaseSummary.payment_status || purchaseSummary.status) && (
            <div className={`result-card ${result?.error ? 'error' : 'success'}`}>
              <span>Buyer outcome</span>
              <strong>{
                result?.error ||
                (purchaseSummary.product || purchaseSummary.order_id || purchaseSummary.total || purchaseSummary.payment_status || purchaseSummary.status
                  ? `Purchased ${purchaseSummary.product || 'the requested item'} for $${Number(purchaseSummary.total || 0).toFixed(2)}.`
                  : result?.message) ||
                'Purchase details received.'
              }</strong>
              {(purchaseSummary.product || purchaseSummary.order_id || purchaseSummary.total || purchaseSummary.payment_status || purchaseSummary.status || purchaseSummary.customer_name || purchaseSummary.shipping_address) && (
                <div className="purchase-summary">
                  {purchaseSummary.product && <div><span className="field-label">Product</span><span>{purchaseSummary.product}</span></div>}
                  {purchaseSummary.total != null && <div><span className="field-label">Total</span><span>${Number(purchaseSummary.total).toFixed(2)}</span></div>}
                  {purchaseSummary.order_id && <div><span className="field-label">Order ID</span><span>#{purchaseSummary.order_id}</span></div>}
                  {purchaseSummary.payment_status && <div><span className="field-label">Payment</span><span>{purchaseSummary.payment_status}</span></div>}
                  {purchaseSummary.status && <div><span className="field-label">Status</span><span>{purchaseSummary.status}</span></div>}
                  {purchaseSummary.customer_name && <div><span className="field-label">Customer</span><span>{purchaseSummary.customer_name}</span></div>}
                  {purchaseSummary.shipping_address && <div><span className="field-label">Shipping</span><span>{purchaseSummary.shipping_address}</span></div>}
                </div>
              )}
            </div>
          )}
          {!isRunning && <button className="upload-button" type="button" onClick={() => fileInput.current?.click()}>{fileName ? 'Upload another' : 'Attach supporting file'}</button>}
        </div>
      </section>
    </main>
  )
}

export default App
