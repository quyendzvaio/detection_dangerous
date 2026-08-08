import { api, authToken } from './api';

export interface CurrentUser {
  id: number;
  gmail: string;
  role: 'USER';
  is_active: boolean;
}

export async function login(gmail: string, password: string) {
  const result = await api<{ access_token: string; token_type: string }>('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ gmail, password }),
  });
  authToken.set(result.access_token);
  return result;
}

export function register(gmail: string, password: string) {
  return api<CurrentUser>('/auth/register', {
    method: 'POST',
    body: JSON.stringify({ gmail, password }),
  });
}

export const getMe = () => api<CurrentUser>('/auth/me');
export const logout = () => authToken.clear();
