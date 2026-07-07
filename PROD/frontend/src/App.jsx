import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { useAuthStore } from './store/authStore';
import Layout from './components/Layout';
import Login from './pages/Login';
import RoutesPage from './pages/Routes';
import Services from './pages/Services';
import Upstreams from './pages/Upstreams';
import Consumers from './pages/Consumers';
import Plugins from './pages/Plugins';
import SSL from './pages/SSL';
import Monitoring from './pages/Monitoring';
import Settings from './pages/Settings';
import SystemInfo from './pages/SystemInfo';
import AuditLog from './pages/AuditLog';
import Notifications from './pages/Notifications';
import Logs from './pages/Logs';

/**
 * ProtectedRoute — redirects to /login if no auth token is present.
 */
function ProtectedRoute({ children }) {
  const token = useAuthStore((state) => state.token);

  if (!token) {
    return <Navigate to="/login" replace />;
  }

  return children;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* Public route */}
        <Route path="/login" element={<Login />} />

        {/* Redirect root to /monitoring */}
        <Route path="/" element={<Navigate to="/monitoring" replace />} />

        {/* Protected routes wrapped in Layout */}
        <Route element={<ProtectedRoute><Layout /></ProtectedRoute>}>
          <Route path="/routes" element={<RoutesPage />} />
          <Route path="/services" element={<Services />} />
          <Route path="/upstreams" element={<Upstreams />} />
          <Route path="/consumers" element={<Consumers />} />
          <Route path="/plugins" element={<Plugins />} />
          <Route path="/ssl" element={<SSL />} />
          <Route path="/monitoring" element={<Monitoring />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/system" element={<SystemInfo />} />
          <Route path="/audit" element={<AuditLog />} />
          <Route path="/notifications" element={<Notifications />} />
          <Route path="/logs" element={<Logs />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
