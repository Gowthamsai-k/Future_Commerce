import { useRef, useState } from 'react'

const API_URL = import.meta.env.VITE_AI_API_URL || '/api/buyer'
const initialPreferences = {
  product_request: '', budget: '2000', quantity: '1', customer_name: 'AI Buyer',
  customer_email: 'ai-buyer@example.com', shipping_address: 'Not provided', payment_method: 'card',
}

function AgentMark() {
  return <span className="agent-mark" aria-hidden="true">✦</span>
}

function App() {
  const [messages, setMessages] = useState([{ id: 1, type: 'agent', text: "Hello. I'm ready to help you find and buy the right product. What are you looking for?" }])
  const [draft, setDraft] = useState('')
  const [preferences, setPreferences] = useState(initialPreferences)
  const [isRunning, setIsRunning] = useState(false)
  const [audit, setAudit] = useState([])
  const [result, setResult] = useState(null)
  const [fileName, setFileName] = useState('')
  const fileInput = useRef(null)

  const updatePreference = (key, value) => setPreferences((current) => ({ ...current, [key]: value }))

  const sendMessage = async (text = draft) => {
    const value = text.trim()
    if (!value || isRunning) return
    const request = preferences.product_request || value
    updatePreference('product_request', request)
    setMessages((current) => [...current, { id: Date.now(), type: 'user', text: value }, { id: Date.now() + 1, type: 'agent', text: 'I am checking your taste, budget, and store inventory now.' }])
    setDraft('')
    setIsRunning(true)
    setResult(null)
    setAudit([])
    try {
      const response = await fetch(API_URL, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...preferences, product_request: request, budget: Number(preferences.budget), quantity: Number(preferences.quantity) }) })
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

  return (
    <main className="app-shell">
      <section className="chat-panel" aria-label="Agent conversation">
        <header className="panel-header"><div className="brand-lockup"><AgentMark /><span>Agent</span></div><button className="header-button" type="button" aria-label="Open agent options">•••</button></header>
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
          {audit.length > 0 && <div className="audit-panel"><div className="audit-heading"><span>Live audit</span><span className={isRunning ? 'pulse status-running' : 'status-done'}>{isRunning ? 'Running' : 'Recorded'}</span></div>{audit.map((item, index) => <div className="audit-item" key={`${item.timestamp}-${index}`}><span className="audit-dot" /><div><strong>{item.event.replaceAll('_', ' ')}</strong><p>{item.detail}</p></div><time>{new Date(item.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</time></div>)}</div>}
          {result?.error && <div className="result-card error"><span>Buyer outcome</span><strong>{result.error}</strong></div>}
          {!isRunning && <button className="upload-button" type="button" onClick={() => fileInput.current?.click()}>{fileName ? 'Upload another' : 'Attach supporting file'}</button>}
        </div>
      </section>
    </main>
  )
}

export default App
