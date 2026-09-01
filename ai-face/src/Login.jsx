import { useState } from 'react'

export default function Login({ onLogin }) {
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [phone, setPhone] = useState('')
  const [address, setAddress] = useState('')
  const [errors, setErrors] = useState({})

  const validateForm = () => {
    const newErrors = {}
    if (!name.trim()) newErrors.name = 'Name is required'
    if (!email.trim()) newErrors.email = 'Email is required'
    else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) newErrors.email = 'Invalid email format'
    if (!phone.trim()) newErrors.phone = 'Phone number is required'
    else if (!/^\d{10,}$/.test(phone.replace(/\D/g, ''))) newErrors.phone = 'Phone must be at least 10 digits'
    if (!address.trim()) newErrors.address = 'Address is required'
    return newErrors
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    const newErrors = validateForm()
    
    if (Object.keys(newErrors).length > 0) {
      setErrors(newErrors)
      return
    }

    // Store in localStorage
    localStorage.setItem('user_name', name.trim())
    localStorage.setItem('user_email', email.trim())
    localStorage.setItem('user_phone', phone.trim())
    localStorage.setItem('user_address', address.trim())
    localStorage.setItem('user_logged_in', 'true')

    onLogin({
      name: name.trim(),
      email: email.trim(),
      phone: phone.trim(),
      address: address.trim(),
    })
  }

  return (
    <main className="login-container">
      <div className="login-card">
        <div className="login-header">
          <h1>Welcome to Gaming Store</h1>
          <p>Sign in or create your profile</p>
        </div>

        <form onSubmit={handleSubmit} className="login-form">
          <div className="form-group">
            <label htmlFor="name">Full Name</label>
            <input
              id="name"
              type="text"
              placeholder="Enter your full name"
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
              placeholder="Enter your email"
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
              placeholder="Enter your phone number"
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
              placeholder="Enter your complete shipping address"
              value={address}
              onChange={(e) => {
                setAddress(e.target.value)
                if (errors.address) setErrors({ ...errors, address: '' })
              }}
              className={errors.address ? 'input-error' : ''}
              rows="4"
            />
            {errors.address && <span className="error-message">{errors.address}</span>}
          </div>

          <button type="submit" className="login-btn">
            Continue to Chat
          </button>
        </form>

        <div className="login-footer">
          <p>Your information is secure and only used for orders</p>
        </div>
      </div>
    </main>
  )
}
