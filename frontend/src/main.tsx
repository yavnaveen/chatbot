import { StrictMode, useEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'

type Conversation = { id: number; title: string; updated_at?: string }
type ChatMessage = { role: 'user' | 'assistant'; content: string; rows?: string[][]; created_at?: string }
type ChatResponse = { success: boolean; answer: string; table?: string[][] | null; conversation_id: number }

const API_BASE = 'http://127.0.0.1:8000'
const DEFAULT_API_KEY = '3Wl2M691mvWR1TsJteWUav8r_n5No3MutqPmRV89D2U'

function getHeaders(customHeaders: Record<string, string> = {}): Record<string, string> {
  const key = localStorage.getItem('tunnel-api-key') || DEFAULT_API_KEY
  return {
    'Content-Type': 'application/json',
    ...(key ? { 'X-API-Key': key } : {}),
    ...customHeaders,
  }
}

function cleanAnswer(text: string): string {
  return text.replace(/<think>[\s\S]*?(<\/think>|$)/g, '').trim()
}

function App() {
  const [question, setQuestion] = useState('')
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [activeId, setActiveId] = useState<number | null>(() => {
    const stored = localStorage.getItem('tunnel-active-conversation')
    return stored ? Number(stored) : null
  })
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [loading, setLoading] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editingTitle, setEditingTitle] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)

  async function loadConversations() {
    const response = await fetch(`${API_BASE}/api/conversations`, { headers: getHeaders() })
    const data: Conversation[] = await response.json()
    setConversations(data)
    if (activeId && data.some((item) => item.id === activeId)) await loadMessages(activeId)
  }

  async function loadMessages(id: number) {
    const response = await fetch(`${API_BASE}/api/conversations/${id}/messages`, { headers: getHeaders() })
    if (!response.ok) throw new Error('Could not load conversation')
    setMessages(await response.json())
  }

  useEffect(() => { void loadConversations().catch(() => undefined) }, [])
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages, loading])

  function selectConversation(id: number) {
    setActiveId(id)
    localStorage.setItem('tunnel-active-conversation', String(id))
    setSidebarOpen(false)
    void loadMessages(id).catch(() => setMessages([]))
  }

  function newChat() {
    setActiveId(null)
    setMessages([])
    localStorage.removeItem('tunnel-active-conversation')
    setSidebarOpen(false)
  }

  async function renameConversation(id: number) {
    const title = editingTitle.trim()
    if (!title) return
    await fetch(`${API_BASE}/api/conversations/${id}`, { method: 'PATCH', headers: getHeaders(), body: JSON.stringify({ title }) })
    setConversations((items) => items.map((item) => item.id === id ? { ...item, title } : item))
    setEditingId(null)
  }

  async function deleteConversation(id: number) {
    await fetch(`${API_BASE}/api/conversations/${id}`, { method: 'DELETE', headers: getHeaders() })
    setConversations((items) => items.filter((item) => item.id !== id))
    if (activeId === id) newChat()
  }

  async function ask() {
    if (!question.trim() || loading) return
    const text = question.trim()
    setQuestion('')
    setMessages((items) => [...items, { role: 'user', content: text }])
    setLoading(true)
    try {
      const response = await fetch(`${API_BASE}/api/chat`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({ question: text, ...(activeId ? { conversation_id: activeId } : {}) }),
      })
      if (!response.ok) throw new Error('Backend error')
      const data: ChatResponse = await response.json()
      if (activeId === null) {
        setActiveId(data.conversation_id)
        localStorage.setItem('tunnel-active-conversation', String(data.conversation_id))
      }
      setMessages((items) => [...items, { role: 'assistant', content: cleanAnswer(data.answer), rows: data.table ?? [] }])
      await loadConversations()
    } catch {
      setMessages((items) => [...items, { role: 'assistant', content: 'I could not connect to the backend. Please start the FastAPI server.', rows: [] }])
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="app-shell">
      <button className="menu-button" onClick={() => setSidebarOpen(!sidebarOpen)} aria-label="Toggle conversations">☰</button>
      <aside className={`sidebar ${sidebarOpen ? 'sidebar-open' : ''}`}>
        <div className="sidebar-head"><span>Conversations</span><button className="new-button" onClick={newChat}>+ New chat</button></div>
        <div className="conversation-list">
          {conversations.map((item) => <div className={`conversation-item ${activeId === item.id ? 'active' : ''}`} key={item.id}>
            {editingId === item.id ? <input autoFocus value={editingTitle} onChange={(event) => setEditingTitle(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') void renameConversation(item.id) }} onBlur={() => void renameConversation(item.id)} /> : <button className="conversation-select" onClick={() => selectConversation(item.id)}>{item.title}</button>}
            <div className="conversation-actions"><button onClick={() => { setEditingId(item.id); setEditingTitle(item.title) }} aria-label="Rename">✎</button><button onClick={() => void deleteConversation(item.id)} aria-label="Delete">×</button></div>
          </div>)}
        </div>
      </aside>
      <section className="chat-panel">
        <header><h1>Tunnel Excavation AI</h1><p>Ask about excavation data or chat normally.</p></header>
        <div className="messages" aria-live="polite">
          {messages.length === 0 && <div className="empty-state">Start a new conversation.</div>}
          {messages.map((message, index) => <div className={`message-row ${message.role}`} key={`${message.created_at ?? 'new'}-${index}`}><div className="bubble">{cleanAnswer(message.content)}{message.rows && message.rows.length > 0 && <div className="table-wrap"><table><thead><tr>{message.rows[0].map((cell) => <th key={cell}>{cell}</th>)}</tr></thead><tbody>{message.rows.slice(1).map((row, rowIndex) => <tr key={rowIndex}>{row.map((cell, cellIndex) => <td key={`${rowIndex}-${cellIndex}`}>{cell}</td>)}</tr>)}</tbody></table></div>}</div></div>)}
          {loading && <div className="message-row assistant"><div className="bubble thinking">Thinking...</div></div>}
          <div ref={bottomRef} />
        </div>
        <div className="composer"><input value={question} onChange={(event) => setQuestion(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') void ask() }} placeholder="Ask about excavation..." aria-label="Question" /><button onClick={() => void ask()} disabled={loading || !question.trim()}>{loading ? 'Thinking...' : 'Ask'}</button></div>
      </section>
    </main>
  )
}

createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>)
