import { createContext, useContext, type ReactNode } from 'react';
import { useChat } from '../hooks/useChat';

const ChatContext = createContext<ReturnType<typeof useChat> | null>(null);

// Holds the chat conversation ABOVE the router so it survives navigating between pages
// (React Router unmounts the Chat route otherwise). Ephemeral by design: a full page
// reload clears it.
export function ChatProvider({ children }: { children: ReactNode }) {
  const chat = useChat();
  return <ChatContext.Provider value={chat}>{children}</ChatContext.Provider>;
}

export function useChatContext() {
  const ctx = useContext(ChatContext);
  if (!ctx) throw new Error('useChatContext must be used within a ChatProvider');
  return ctx;
}
