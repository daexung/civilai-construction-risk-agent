import { ChatResponse, ChoiceValue } from './types';

const API_BASE = process.env.REACT_APP_API_URL ?? '';

export interface ChatRequestBody {
  thread_id?: string | null;
  message?: string;
  answers?: Record<string, ChoiceValue>;
  basis_date?: string;
}

export async function sendChat(body: ChatRequestBody): Promise<ChatResponse> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  } catch {
    throw new Error('NETWORK_ERROR');
  }
  if (!res.ok) {
    throw new Error(res.status >= 500 ? 'SERVER_ERROR' : 'REQUEST_ERROR');
  }
  return res.json();
}
