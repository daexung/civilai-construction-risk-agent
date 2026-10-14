import { authClient } from './auth';

async function request<T>(path: string, signal?: AbortSignal): Promise<T> {
  const { data, error } = await authClient?.auth.getSession() ?? { data: { session: null }, error: null };
  if (error || !data.session?.access_token) throw Object.assign(new Error('로그인이 필요합니다.'), { status: 401 });
  const response = await fetch(`${process.env.REACT_APP_API_URL ?? ''}/api/admin${path}`, {
    headers: { Authorization: `Bearer ${data.session.access_token}`, Accept: 'application/json' },
    cache: 'no-store', signal,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const message = response.status === 401 ? '로그인이 필요합니다.'
      : response.status === 403 ? '이 계정에는 운영자 권한이 없습니다.'
        : response.status >= 500 ? '운영 자료를 불러오지 못했습니다.' : (body.detail ?? '요청을 처리하지 못했습니다.');
    throw Object.assign(new Error(message), { status: response.status });
  }
  return response.json();
}

const query = (values: Record<string, string | number | undefined>) => {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => { if (value !== undefined && value !== '') params.set(key, String(value)); });
  return params.toString() ? `?${params}` : '';
};

export const adminApi = {
  summary: (period: string, signal?: AbortSignal) => request<any>(`/summary${query({ period })}`, signal),
  ratings: (filters: Record<string, string | number | undefined>, signal?: AbortSignal) => request<any>(`/answer-feedback${query(filters)}`, signal),
  rating: (id: string, signal?: AbortSignal) => request<any>(`/answer-feedback/${encodeURIComponent(id)}`, signal),
  feedback: (filters: Record<string, string | number | undefined>, signal?: AbortSignal) => request<any>(`/feedback${query(filters)}`, signal),
  feedbackDetail: (id: string, signal?: AbortSignal) => request<any>(`/feedback/${encodeURIComponent(id)}`, signal),
  runs: (filters: Record<string, string | number | undefined>, signal?: AbortSignal) => request<any>(`/runs${query(filters)}`, signal),
  run: (id: string, signal?: AbortSignal) => request<any>(`/runs/${encodeURIComponent(id)}`, signal),
};
