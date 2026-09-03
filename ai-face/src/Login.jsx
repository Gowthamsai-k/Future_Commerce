import { useState, useEffect } from 'react'

export default function Login({ onLogin }) {
  const [mode, setMode] = useState('login') // 'login' or 'signup'
  const [savedAccounts, setSavedAccounts] = useState({})
  
  // Login form state
  const [loginEmail, setLoginEmail] = useState('')
  
  // Signup form state
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [phone, setPhone] = useState('')
  const [address, setAddress] = useState('')
  const [errors, setErrors] = useState({})

  useEffect(() => {
    try {
      const stored = localStorage.getItem('registered_accounts')
      let accounts = {}
      if (stored) {
        accounts = JSON.parse(stored)
      }
      
      // Migration check: If single old user profile exists in localStorage, migrate it to accounts map
      const oldEmail = localStorage.getItem('user_email')
      const oldName = localStorage.getItem('user_name')
      if (oldEmail && oldName && !accounts[oldEmail.toLowerCase()]) {
        accounts[oldEmail.toLowerCase()] = {
          name: oldName,
          email: oldEmail.toLowerCase(),
          phone: localStorage.getItem('user_phone') || '',
          address: localStorage.getItem('user_address') || '',
        }
        localStorage.setItem('registered_accounts', JSON.stringify(accounts))
      }

      setSavedAccounts(accounts)
      const emails = Object.keys(accounts)
      if (emails.length > 0) {
        setLoginEmail(emails[emails.length - 1])
      } else {
        setMode('signup') // If no accounts exist yet, default to Sign Up
      }
    } catch {
      // Fallback
    }
  }, [])

  const handleQuickLogin = (account) => {
    localStorage.setItem('user_name', account.name)
    localStorage.setItem('user_email', account.email)
    localStorage.setItem('user_phone', account.phone || '')
    localStorage.setItem('user_address', account.address || '')
    localStorage.setItem('user_logged_in', 'true')
    onLogin(account)
  }

  const handleLoginSubmit = (e) => {
    e.preventDefault()
    const cleanEmail = loginEmail.trim().toLowerCase()
    if (!cleanEmail) {
      setErrors({ loginEmail: 'Please enter your email address' })
      return
    }

    const account = savedAccounts[cleanEmail]
    if (!account) {
      setErrors({ loginEmail: 'Account not found. Please switch to Sign Up to create your profile!' })
      return
    }

    handleQuickLogin(account)
  }

  const validateSignup = () => {
    const newErrors = {}
    if (!name.trim()) newErrors.name = 'Full name is required'
    if (!email.trim()) newErrors.email = 'Email is required'
    else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) newErrors.email = 'Invalid email format'
    if (!phone.trim()) newErrors.phone = 'Phone number is required'
    else if (!/^\d{10,}$/.test(phone.replace(/\D/g, ''))) newErrors.phone = 'Phone must be at least 10 digits'
    if (!address.trim()) newErrors.address = 'Shipping address is required'
    return newErrors
  }

  const handleSignupSubmit = (e) => {
    e.preventDefault()
    const newErrors = validateSignup()
    if (Object.keys(newErrors).length > 0) {
      setErrors(newErrors)
      return
    }

    const cleanEmail = email.trim().toLowerCase()
    const newAccount = {
      name: name.trim(),
      email: cleanEmail,
      phone: phone.trim(),
      address: address.trim(),
    }

    // Save into registered accounts dictionary
    const updated = { ...savedAccounts, [cleanEmail]: newAccount }
    localStorage.setItem('registered_accounts', JSON.stringify(updated))

    // Automatically set as active logged in user
    handleQuickLogin(newAccount)
  }

  const accountList = Object.values(savedAccounts)

  return (
    <main className="login-container">
      <div className="login-card">
        <div className="login-header">
          <h1>✦ Gaming Store</h1>
          <p>{mode === 'login' ? 'Welcome back! Sign in to your account' : 'Create your buyer profile once'}</p>
        </div>

        <div className="auth-tabs" role="tablist">
          <button
            type="button"
            className={`auth-tab ${mode === 'login' ? 'active' : ''}`}
            onClick={() => { setMode('login'); setErrors({}); }}
          >
            Log In
          </button>
          <button
            type="button"
            className={`auth-tab ${mode === 'signup' ? 'active' : ''}`}
            onClick={() => { setMode('signup'); setErrors({}); }}
          >
            Sign Up
          </button>
        </div>

        {mode === 'login' ? (
          <form onSubmit={handleLoginSubmit} className="login-form">
            {accountList.length > 0 && (
              <div className="quick-accounts">
                <span className="quick-label">Saved Accounts (Click to log in):</span>
                <div className="quick-list">
                  {accountList.map((acc) => (
                    <button
                      key={acc.email}
                      type="button"
                      className="quick-account-btn"
                      onClick={() => handleQuickLogin(acc)}
                    >
                      <div className="acc-info">
                        <strong>{acc.name}</strong>
                        <small>{acc.email}</small>
                      </div>
                      <span className="acc-arrow">→</span>
                    </button>
                  ))}
                </div>
              </div>
            )}

            <div className="form-group">
              <label htmlFor="loginEmail">Email Address</label>
              <input
                id="loginEmail"
                type="email"
                placeholder="Enter your registered email"
                value={loginEmail}
                onChange={(e) => {
                  setLoginEmail(e.target.value)
                  if (errors.loginEmail) setErrors({ ...errors, loginEmail: '' })
                }}
                className={errors.loginEmail ? 'input-error' : ''}
              />
              {errors.loginEmail && <span className="error-message">{errors.loginEmail}</span>}
            </div>

            <button type="submit" className="login-btn">
              Log In & Start Shopping
            </button>
          </form>
        ) : (
          <form onSubmit={handleSignupSubmit} className="login-form">
            <div className="form-group">
              <label htmlFor="name">Full Name</label>
              <input
                id="name"
                type="text"
                placeholder="e.g. Gowtham Vithal Sai"
                value={name}
                onChange={(e) => {
                  setName(e.target.value)
                  if (errors.name) setErrors({ ...errors, name: '' })
                }}
                className={errors.name ? 'input-error' : ''}
              />
              {errors.name && <span className="error-message">{errors.name}</span>}
            </div>

            <div className="form-group">
              <label htmlFor="email">Email Address</label>
              <input
                id="email"
                type="email"
                placeholder="gowtham@example.com"
                value={email}
                onChange={(e) => {
                  setEmail(e.target.value)
                  if (errors.email) setErrors({ ...errors, email: '' })
                }}
                className={errors.email ? 'input-error' : ''}
              />
              {errors.email && <span className="error-message">{errors.email}</span>}
            </div>

            <div className="form-group">
              <label htmlFor="phone">Phone Number</label>
              <input
                id="phone"
                type="tel"
                placeholder="9876543210"
                value={phone}
                onChange={(e) => {
                  setPhone(e.target.value)
                  if (errors.phone) setErrors({ ...errors, phone: '' })
                }}
                className={errors.phone ? 'input-error' : ''}
              />
              {errors.phone && <span className="error-message">{errors.phone}</span>}
            </div>

            <div className="form-group">
              <label htmlFor="address">Shipping Address</label>
              <textarea
                id="address"
                placeholder="Enter complete shipping address"
                value={address}
                onChange={(e) => {
                  setAddress(e.target.value)
                  if (errors.address) setErrors({ ...errors, address: '' })
                }}
                className={errors.address ? 'input-error' : ''}
                rows="3"
              />
              {errors.address && <span className="error-message">{errors.address}</span>}
            </div>

            <button type="submit" className="login-btn">
              Create Account & Log In
            </button>
          </form>
        )}

        <div className="login-footer">
          <p>Your saved account profile is retained automatically on this device.</p>
        </div>
      </div>
    </main>
  )
}
