import { useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import apisixLogo from '../assets/apisix_logo.png';

export default function Login() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [searchParams] = useSearchParams();
  const sessionTimeout = searchParams.get('reason') === 'timeout';

  const { login } = useAuth();
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      await login(username, password);
      navigate('/monitoring');
    } catch (err) {
      if (err.response && err.response.status === 401) {
        setError('Invalid username or password');
      } else {
        setError('An unexpected error occurred. Please try again.');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex">
      {/* Left panel — branding (red/dark gradient) */}
      <div className="hidden lg:flex lg:w-1/2 bg-gradient-to-br from-red-700 via-red-800 to-gray-900 relative overflow-hidden">
        {/* Decorative shapes */}
        <div className="absolute top-0 left-0 w-full h-full opacity-10">
          <div className="absolute top-[-10%] left-[-10%] w-[60%] h-[60%] rounded-full bg-white" />
          <div className="absolute bottom-[-20%] right-[-10%] w-[50%] h-[50%] rounded-full bg-white" />
        </div>

        {/* Content */}
        <div className="relative z-10 flex flex-col items-center justify-center w-full px-12 text-white">
          {/* Single large APISIX logo */}
          <div className="mb-12 bg-white rounded-2xl p-6 shadow-lg">
            <img
              src={apisixLogo}
              alt="CRO IT APISIX Dashboard"
              className="w-64 h-64 object-contain"
            />
          </div>

          {/* Title */}
          <h2 className="text-3xl font-bold text-center mb-2">
            CRO IT
          </h2>
          <p className="text-lg text-red-200 text-center mb-10">
            APISIX Dashboard
          </p>

          {/* Feature list */}
          <div className="space-y-3 text-sm">
            <div className="flex items-center gap-3">
              <svg className="w-5 h-5 text-red-300 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <span>Real-time route management</span>
            </div>
            <div className="flex items-center gap-3">
              <svg className="w-5 h-5 text-red-300 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <span>SSL certificate monitoring</span>
            </div>
            <div className="flex items-center gap-3">
              <svg className="w-5 h-5 text-red-300 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <span>Pod metrics &amp; health dashboards</span>
            </div>
            <div className="flex items-center gap-3">
              <svg className="w-5 h-5 text-red-300 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <span>Role-based access control</span>
            </div>
          </div>
        </div>
      </div>

      {/* Right panel — login form */}
      <div className="flex-1 flex flex-col items-center justify-center bg-gray-50 px-6 py-12">
        <div className="w-full max-w-md">
          {/* Mobile logo (shown on small screens) */}
          <div className="lg:hidden flex items-center justify-center mb-8">
            <div className="bg-white rounded-xl p-4 shadow">
              <img src={apisixLogo} alt="APISIX Logo" className="h-16 object-contain" />
            </div>
          </div>

          <h2 className="text-2xl font-bold text-gray-900 mb-2">
            Sign in to Dashboard
          </h2>
          <p className="text-sm text-gray-500 mb-8">
            Enter your credentials to continue
          </p>

          <form onSubmit={handleSubmit} className="space-y-5">
            {sessionTimeout && (
              <div className="bg-yellow-50 border border-yellow-200 text-yellow-700 px-4 py-3 rounded-md text-sm" role="alert">
                Your session has expired due to inactivity. Please sign in again.
              </div>
            )}

            {error && (
              <div
                className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-md text-sm"
                role="alert"
              >
                {error}
              </div>
            )}

            <div>
              <label
                htmlFor="username"
                className="block text-xs font-semibold text-gray-600 uppercase tracking-wide mb-2"
              >
                Username
              </label>
              <input
                id="username"
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
                autoComplete="username"
                className="w-full px-4 py-3 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-red-500 focus:border-red-500 text-sm"
                placeholder="Enter username"
              />
            </div>

            <div>
              <label
                htmlFor="password"
                className="block text-xs font-semibold text-gray-600 uppercase tracking-wide mb-2"
              >
                Password
              </label>
              <input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                autoComplete="current-password"
                className="w-full px-4 py-3 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-red-500 focus:border-red-500 text-sm"
                placeholder="Enter password"
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full py-3 px-4 bg-red-700 hover:bg-red-800 disabled:bg-red-400 disabled:cursor-not-allowed text-white font-semibold rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2 transition-colors text-sm"
            >
              {loading ? 'Signing in...' : 'Sign In'}
            </button>
          </form>

          {/* Footer */}
          <div className="mt-8 p-3 bg-gray-100 rounded-md border border-gray-200">
            <p className="text-xs text-gray-500 text-center leading-relaxed">
              <strong>AUTHORIZED USE ONLY.</strong> This system is the property of FNB / CRO IT.
              Unauthorized access is prohibited and may be subject to disciplinary action and/or prosecution.
              All activities are monitored and logged for security purposes.
            </p>
          </div>

          <p className="mt-4 text-center text-xs text-gray-400">
            CRO IT APISIX Dashboard &middot; FNB &copy; {new Date().getFullYear()}
          </p>
          <p className="mt-1 text-center text-xs text-gray-400">
            Created by CRO IT
          </p>
        </div>
      </div>
    </div>
  );
}
