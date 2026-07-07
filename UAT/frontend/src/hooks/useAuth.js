import { useAuthStore } from '../store/authStore';
import apiClient from '../api/client';

export function useAuth() {
  const { token, user, role, setAuth, clearAuth } = useAuthStore();

  const isAuthenticated = !!token;

  const login = async (username, password) => {
    const { data } = await apiClient.post('/auth/login', { username, password });
    const accessToken = data.access_token;

    // Fetch user info with the new token
    const meResponse = await apiClient.get('/auth/me', {
      headers: { Authorization: `Bearer ${accessToken}` },
    });

    const { username: userName, role: userRole } = meResponse.data;
    setAuth(accessToken, userName, userRole);
  };

  const logout = async () => {
    try {
      await apiClient.post('/auth/logout');
    } finally {
      clearAuth();
      window.location.href = '/login';
    }
  };

  return { user, role, isAuthenticated, login, logout };
}