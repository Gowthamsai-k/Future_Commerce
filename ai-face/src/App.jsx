import { useState, useRef, useEffect } from 'react'
import { marked } from 'marked'
import Login from './Login'

const API_URL = import.meta.env.VITE_AI_API_URL || '/api/buyer'

const getGreeting = () => {
  const hour = new Date().getHours()

  if (hour < 12) return 'Good morning! I can help you shop and place a purchase. What would you like to buy?'
  if (hour < 18) return 'Good afternoon! I can help you shop and place a purchase. What would you like to buy?'
  return 'Good evening! I can help you shop and place a purchase. What would you like to buy?'
}

const buildRequestPayload = (request, userDetails, conversationHistory) => ({
  product_request: request.trim(),
  customer_name: userDetails.name,
  customer_email: userDetails.email,
  shipping_address: userDetails.address,
  payment_method: userDetails.payment_method || 'razorpay',
  conversation_history: conversationHistory,
})

const detectPipelineType = (message) => {
  const text = message.toLowerCase()
  const queryWords = ['list', 'show', 'available', 'search', 'browse', 'find', 'what products', 'check products', 'order history', 'my orders', 'check my order', 'look up', 'catalog']
  const purchaseWords = ['buy', 'order', 'purchase', 'checkout', 'pay', 'place order', 'buy now', 'need this', 'get me']

  if (queryWords.some((word) => text.includes(word))) return 'query'
  if (purchaseWords.some((word) => text.includes(word))) return 'purchase'
  return 'normal'
}

const parsePurchaseSummary = (data) => {
  const message = typeof data?.message === 'string' ? data.message.trim() : ''
  const error = typeof data?.error === 'string' ? data.error.trim() : ''
  const summary = data?.summary ?? {}

  return {
    message,
    error,
    product: summary.product || '',
    total: summary.total ?? null,
    order_id: summary.order_id ?? null,
    payment_status: summary.payment_status || '',
    status: summary.status || '',
    razorpay_order_id: summary.razorpay_order_id || '',
    razorpay_payment_id: summary.razorpay_payment_id || '',
  }
}

const formatResultAsMarkdown = (summary) => {
  let markdown = ''
  
  if (summary.error) {
    markdown = `**❌ Error**\n\n${summary.error}`
  } else if (summary.message) {
    markdown = `**✅ ${summary.message}**\n\n`
    markdown += '| Field | Value |\n|-------|-------|\n'
    if (summary.product) markdown += `| Product | ${summary.product} |\n`
    if (summary.total != null) markdown += `| Total | ₹${Number(summary.total).toFixed(2)} |\n`
    if (summary.order_id) markdown += `| Order ID | #${summary.order_id} |\n`
    if (summary.payment_status) markdown += `| Payment Status | ${summary.payment_status} |\n`
    if (summary.status) markdown += `| Order Status | ${summary.status} |\n`
    if (summary.razorpay_order_id) markdown += `| Razorpay Order ID | \`${summary.razorpay_order_id}\` |\n`
    if (summary.razorpay_payment_id) markdown += `| Razorpay Payment ID | \`${summary.razorpay_payment_id}\` |\n`
  } else {
    markdown = '**Summary**'
  }
  
  return marked(markdown)
}

const detectFollowUpQuestion = (text) => {
  const lower = text.toLowerCase()
  
  // OTP Verification Prompt (Highest Priority)
  if (lower.includes('otp') || lower.includes('one time password') || lower.includes('authorize payment') || lower.includes('provide your otp')) {
    return {
      type: 'otp_prompt',
      buttons: ['1111', '1234', '111111', 'Cancel Order'],
    }
  }
  
  // Disambiguation / Choice between items (e.g. "Which headset would you like... ID 4 or ID 5")
  if ((lower.includes('which') || lower.includes('choose') || lower.includes('select') || lower.includes('or')) && lower.includes('?')) {
    const choices = []
    if (lower.includes('hyperx') || text.includes('HyperX')) choices.push('HyperX Cloud Stinger 2')
    if (lower.includes('logitech') || text.includes('Logitech')) choices.push('Logitech G435 Wireless')
    if (lower.includes('razer') || text.includes('Razer')) choices.push('Razer DeathAdder Essential')
    if (lower.includes('redragon') || text.includes('Redragon')) choices.push('Redragon K552')
    if (choices.length >= 2) {
      return {
        type: 'choice',
        buttons: choices,
      }
    }
    // If it's a "Which" choice question, don't generate incorrect Yes/No buttons
    return null
  }

  // Asking about quantity to buy (highest priority - most common case)
  if ((lower.includes('how many') || lower.includes('quantity') || lower.includes('how much')) && 
      lower.includes('?')) {
    return {
      type: 'quantity',
      buttons: ['1', '2', '5', '10', 'Cancel'],
    }
  }
  
  // Asking about proceeding/confirmation with product in budget (don't offer budget adjustment)
  if ((lower.includes('proceed') || lower.includes('checkout') || lower.includes('confirm') || lower.includes('buy this')) && lower.includes('?')) {
    return {
      type: 'yes_no',
      buttons: ['Yes, buy it', 'No, cancel'],
    }
  }
  
  // Budget increase ONLY if it explicitly mentions not fitting budget
  if ((lower.includes('increase') || lower.includes('exceed') || lower.includes('over budget')) && 
      (lower.includes('?') || lower.includes('budget')) &&
      (lower.includes('more') || lower.includes('higher') || lower.includes('cannot') || lower.includes('too much') || lower.includes('exceed'))) {
    return {
      type: 'budget_adjustment',
      buttons: ['Yes, increase budget', 'No, search lower', 'Show alternatives'],
    }
  }
  
  // Product selection from alternatives
  if ((lower.includes('alternative') || lower.includes('instead') || lower.includes('option')) && 
      lower.includes('?')) {
    return {
      type: 'alternative_selection',
      buttons: ['Accept this', 'Look for more', 'Try different budget'],
    }
  }
  
  // Generic yes/no ONLY for explicit confirmation questions
  if (lower.includes('?') && (lower.includes('would you like to proceed') || lower.includes('would you like to buy') || lower.includes('shall i place'))) {
    return {
      type: 'yes_no',
      buttons: ['Yes', 'No'],
    }
  }
  
  return null
}

const getNaturalLoadingMessage = (text) => {
  const lower = text.toLowerCase()
  if (lower.includes('buy') || lower.includes('order') || lower.includes('checkout') || lower.includes('pay') || lower.includes('yes')) {
    const purchasePhrases = [
      'Processing your purchase request...',
      'Checking inventory and setting up your order...',
      'Preparing your order & payment details...',
      'Reserving item and preparing checkout...',
    ]
    return purchasePhrases[Math.floor(Math.random() * purchasePhrases.length)]
  }
  if (lower.includes('list') || lower.includes('show') || lower.includes('catalog') || lower.includes('available')) {
    const listPhrases = [
      'Fetching available store catalog...',
      'Checking current store inventory...',
      'Gathering available products for you...',
    ]
    return listPhrases[Math.floor(Math.random() * listPhrases.length)]
  }
  if (lower.includes('search') || lower.includes('find') || lower.includes('look') || lower.includes('under') || lower.includes('budget')) {
    const searchPhrases = [
      'Searching products within your budget...',
      'Looking for matching items in stock...',
      'Finding the best options for you...',
    ]
    return searchPhrases[Math.floor(Math.random() * searchPhrases.length)]
  }
  const defaultPhrases = [
    'Checking with the store assistant...',
    'Looking into that for you...',
    'Consulting the store inventory...',
  ]
  return defaultPhrases[Math.floor(Math.random() * defaultPhrases.length)]
}

function App() {
  const [isLoggedIn, setIsLoggedIn] = useState(localStorage.getItem('user_logged_in') === 'true')
  const [messages, setMessages] = useState([{ id: 1, type: 'agent', text: getGreeting() }])
  const [draft, setDraft] = useState('')
  const [isRunning, setIsRunning] = useState(false)
  const [result, setResult] = useState(null)
  const [audit, setAudit] = useState([])
  const [pipelineType, setPipelineType] = useState('purchase')
  const conversationRef = useRef(null)
  const auditListRef = useRef(null)
  const isAtBottomRef = useRef(true)
  const [userDetails, setUserDetails] = useState({
    name: localStorage.getItem('user_name') || 'Guest',
    email: localStorage.getItem('user_email') || '',
    address: localStorage.getItem('user_address') || '',
    phone: localStorage.getItem('user_phone') || '',
    payment_method: 'razorpay',
  })

  const purchaseSummary = parsePurchaseSummary(result)

  const handleLogin = (details) => {
    setUserDetails({
      ...details,
      payment_method: 'razorpay',
    })
    setIsLoggedIn(true)
  }

  const handleLogout = () => {
    localStorage.removeItem('user_logged_in')
    localStorage.removeItem('user_name')
    localStorage.removeItem('user_email')
    localStorage.removeItem('user_phone')
    localStorage.removeItem('user_address')
    setIsLoggedIn(false)
    setMessages([{ id: 1, type: 'agent', text: getGreeting() }])
    setDraft('')
    setResult(null)
    setAudit([])
    setUserDetails({
      name: 'Guest',
      email: '',
      address: '',
      phone: '',
      payment_method: 'razorpay',
    })
  }

  const handleScroll = () => {
    if (conversationRef.current) {
      const { scrollTop, scrollHeight, clientHeight } = conversationRef.current
      // Check if scrolled to bottom (within 50px tolerance)
      isAtBottomRef.current = scrollHeight - scrollTop - clientHeight < 50
    }
  }

  useEffect(() => {
    if (conversationRef.current) {
      conversationRef.current.addEventListener('scroll', handleScroll)
      return () => conversationRef.current?.removeEventListener('scroll', handleScroll)
    }
  }, [])

  const scrollToBottom = (smooth = true) => {
    if (conversationRef.current) {
      conversationRef.current.scrollTo({
        top: conversationRef.current.scrollHeight,
        behavior: smooth ? 'smooth' : 'auto',
      })
    }
  }

  useEffect(() => {
    if (conversationRef.current && isAtBottomRef.current) {
      setTimeout(() => {
        scrollToBottom(true)
      }, 50)
    }
  }, [messages])

  useEffect(() => {
    if (auditListRef.current) {
      auditListRef.current.scrollTop = auditListRef.current.scrollHeight
    }
  }, [audit])

  const getConversationHistory = () => {
    return messages
      .filter((msg) => !msg.isLoading)
      .map((msg) => ({ role: msg.type === 'user' ? 'user' : 'assistant', content: msg.text }))
  }

  const sendMessage = async (text = draft) => {
    const value = text.trim()
    if (!value || isRunning) return

    const userId = Date.now()
    const loadingId = userId + 1

    setPipelineType(detectPipelineType(value))
    isAtBottomRef.current = true

    setMessages((current) => [
      ...current,
      { id: userId, type: 'user', text: value },
      { id: loadingId, type: 'agent', text: getNaturalLoadingMessage(value), isLoading: true },
    ])
    setDraft('')
    setIsRunning(true)
    setResult(null)
    setAudit([])

    setTimeout(() => scrollToBottom(true), 30)

    try {
      const response = await fetch(API_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(buildRequestPayload(value, userDetails, getConversationHistory())),
      })

      if (!response.ok || !response.body) {
        let detail = `The service returned HTTP ${response.status}`
        try {
          const errorData = await response.json()
          detail = errorData.error || detail
        } catch {
          // Ignore JSON parse failures and keep the HTTP message.
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
      const agentMessage = data.message || data.error || 'I could not complete that purchase request.'
      const suggestions = detectFollowUpQuestion(agentMessage)
      
      setMessages((current) =>
        current.map((msg) =>
          msg.id === loadingId
            ? {
                id: loadingId,
                type: 'agent',
                text: agentMessage,
                suggestions: suggestions?.buttons || null,
                suggestionType: suggestions?.type || null,
                isLoading: false,
              }
            : msg
        )
      )
    } catch (error) {
      const detail = error instanceof Error ? error.message : 'Unable to reach the AI buyer service.'
      setResult({ error: detail })
      setMessages((current) =>
        current.map((msg) =>
          msg.id === loadingId
            ? { id: loadingId, type: 'agent', text: detail, isLoading: false }
            : msg
        )
      )
    } finally {
      setIsRunning(false)
      setTimeout(() => scrollToBottom(true), 50)
    }
  }

  if (!isLoggedIn) {
    return <Login onLogin={handleLogin} />
  }

  return (
    <main className="app-shell simple-chat-shell">
      <section className="chat-panel simple-chat-panel" aria-label="Shopping chat">
        <header className="panel-header simple-header">
          <div className="brand-lockup">
            <span className="agent-mark" aria-hidden="true">✦</span>
            <div className="header-info">
              <span className="user-name">{userDetails.name}</span>
              <button className="logout-btn" onClick={handleLogout} title="Logout">
                ✕
              </button>
            </div>
          </div>
        </header>

        <div className="conversation simple-conversation" ref={conversationRef}>
          {messages.map((message) => (
            <article className={`message ${message.type}`} key={message.id}>
              {message.type === 'agent' && <span className="agent-mark" aria-hidden="true">✦</span>}
              <div className="message-body">
                {message.type === 'agent' ? (
                  <>
                    <div className="markdown-content" dangerouslySetInnerHTML={{ __html: marked(message.text) }} />
                    {message.suggestions && (
                      <div className="suggestion-buttons">
                        {message.suggestions.map((btn, idx) => (
                          <button
                            key={idx}
                            className="suggestion-btn"
                            onClick={() => sendMessage(btn)}
                            disabled={isRunning}
                          >
                            {btn}
                          </button>
                        ))}
                      </div>
                    )}
                  </>
                ) : (
                  <p>{message.text}</p>
                )}
              </div>
            </article>
          ))}
        </div>

        <form
          className="composer simple-composer"
          onSubmit={(event) => {
            event.preventDefault()
            sendMessage()
          }}
        >
          <textarea
            disabled={isRunning}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault()
                sendMessage()
              }
            }}
            placeholder={isRunning ? 'Checking your purchase request...' : 'Tell me what you want to buy...'}
            aria-label="Message"
            rows="1"
          />
          <button className="send-button" type="submit" disabled={isRunning} aria-label="Send message">
            {isRunning ? '…' : '➤'}
          </button>
        </form>
      </section>

      <aside className="workspace-panel pipeline-panel" aria-label="Transaction details">
        <header className="workspace-header">
          <span>Transaction details</span>
          <span className={`status-pill ${isRunning ? 'status-running' : result?.error ? 'status-failed' : result ? 'status-done' : 'status-idle'}`}>
            {isRunning ? 'running' : result?.error ? 'failed' : result ? 'done' : 'ready'}
          </span>
        </header>

        <div className="pipeline-content">
          <div className="audit-panel animated-audit">
            <div className="audit-heading">
              <span>Live audit</span>
              <span className={`pulse ${isRunning ? 'status-running' : result?.error ? 'status-failed' : 'status-done'}`}>
                {isRunning ? 'live' : result?.error ? 'error' : result ? 'complete' : 'idle'}
              </span>
            </div>

            {audit.length > 0 ? (
              <div className="audit-list" ref={auditListRef}>
                {audit.map((item, index) => (
                  <div className="audit-item" key={`audit-${index}`}>
                    <span className="audit-dot" aria-hidden="true" />
                    <div>
                      <strong>{item?.event?.replaceAll('_', ' ') || 'event'}</strong>
                      <p>{item?.detail || item?.event || 'Processing...'}</p>
                    </div>
                    <time>{item?.timestamp ? new Date(item.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : 'now'}</time>
                  </div>
                ))}
              </div>
            ) : (
              <div className="audit-placeholder">
                <p>Awaiting the next purchase event...</p>
              </div>
            )}
          </div>

          {result && (
            <div className={`result-card ${purchaseSummary.error ? 'error' : 'success'} simple-result`}>
              <div className="markdown-content" dangerouslySetInnerHTML={{ __html: formatResultAsMarkdown(purchaseSummary) }} />
            </div>
          )}
        </div>
      </aside>
    </main>
  )
}

export default App
