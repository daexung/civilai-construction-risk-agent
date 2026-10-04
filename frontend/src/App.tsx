import React, { useCallback, useState } from 'react';
import { v4 as uuidv4 } from 'uuid';
import ChatArea from './components/ChatArea';
import ToastContainer from './components/ToastContainer';
import { ChatTurn, ChoiceValue } from './types';
import { sendChat } from './api';
import { showToast } from './toast';
import './App.css';

export default function App() {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [threadId, setThreadId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleError = useCallback((err: unknown) => {
    const msg = err instanceof Error ? err.message : '';
    const text =
      msg === 'NETWORK_ERROR' ? '네트워크 연결을 확인해주세요.' :
      msg === 'SERVER_ERROR'  ? '서버 오류가 발생했습니다. 잠시 후 다시 시도해주세요.' :
                                 'API 서버에 연결할 수 없습니다. 서버가 켜져 있는지 확인해주세요.';
    showToast(text, 'error');
  }, []);

  const send = useCallback(async (
    userLabel: string,
    body: { message?: string; answers?: Record<string, ChoiceValue> },
    thread: string | null,
  ) => {
    const startedAt = performance.now();
    const userTurn: ChatTurn = { id: uuidv4(), role: 'user', text: userLabel, sentAtMs: Date.now() };
    setTurns(prev => [...prev, userTurn]);
    setLoading(true);
    try {
      const response = await sendChat({ thread_id: thread, ...body });
      setThreadId(response.thread_id);
      setTurns(prev => [...prev, { id: uuidv4(), role: 'assistant', response,
        elapsedMs: performance.now() - startedAt, receivedAtMs: Date.now() }]);
    } catch (err) {
      handleError(err);
    } finally {
      setLoading(false);
    }
  }, [handleError]);

  const handleSendMessage = useCallback((text: string) => send(text, { message: text }, threadId), [send, threadId]);

  const handleSendAnswers = useCallback((answers: Record<string, ChoiceValue>, summary: string) => {
    return send(summary, { answers }, threadId);
  }, [send, threadId]);

  // 결과 카드의 조건만 바꿔 같은 카드를 새 계산으로 교체한다(공종 입력은 서버가 그대로 둔다).
  const handleChangeConditions = useCallback(async (turnId: string, conditions: Record<string, string>) => {
    if (!threadId) return;
    const startedAt = performance.now();
    setLoading(true);
    try {
      const response = await sendChat({ thread_id: threadId, conditions });
      setTurns(prev => prev.map(turn => (turn.id === turnId ? { ...turn, response,
        elapsedMs: performance.now() - startedAt, receivedAtMs: Date.now() } : turn)));
    } catch (err) {
      handleError(err);
    } finally {
      setLoading(false);
    }
  }, [threadId, handleError]);

  const handleNewChat = useCallback(() => {
    setThreadId(null);
    setTurns([]);
  }, []);

  const handleSendExample = useCallback((text: string) => {
    setTurns([]);
    setThreadId(null);
    return send(text, { message: text }, null);
  }, [send]);

  return (
    <div className="app">
      <ToastContainer />
      <ChatArea
        turns={turns}
        loading={loading}
        onSendMessage={handleSendMessage}
        onSendAnswers={handleSendAnswers}
        onChangeConditions={handleChangeConditions}
        onNewChat={handleNewChat}
        onSendExample={handleSendExample}
      />
    </div>
  );
}
