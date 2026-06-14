import { createContext, useContext } from 'react';
import type { useChat } from '../hooks/useChat';

export const ChatContext = createContext<ReturnType<typeof useChat> | null>(null);

export function useChatContext() {
  const ctx = useContext(ChatContext);
  if (!ctx) throw new Error('useChatContext must be used within a ChatProvider');
  return ctx;
}
