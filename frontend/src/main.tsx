import { StrictMode, useEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'

type Conversation = { id: number; title: string; updated_at?: string }
type ChatMessage = {
  role: 'user' | 'assistant'
  content: string
  rows?: string[][]
  generated_query?: string | null
  created_at?: string
}
type ChatResponse = {
  success: boolean
  answer: string
  table?: string[][] | null
  conversation_id: number
  generated_query?: string | null
}

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

function exportToCsv(rows: string[][], filename = `excavation_data_${Date.now()}.csv`) {
  const csvContent = rows
    .map((row) => row.map((cell) => `"${String(cell ?? '').replace(/"/g, '""')}"`).join(','))
    .join('\r\n')
  const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

function SvgChart({ rows }: { rows: string[][] }) {
  if (!rows || rows.length < 2) return null
  const headers = rows[0]
  const data = rows.slice(1, 15) // display up to 14 entries for optimal layout

  let labelIdx = headers.findIndex((h) => /date|tarikh|class|support/i.test(h))
  if (labelIdx === -1) labelIdx = 0

  let actualIdx = headers.findIndex((h) => /actual/i.test(h))
  let theoIdx = headers.findIndex((h) => /theo/i.test(h))
  if (actualIdx === -1 && theoIdx === -1) {
    actualIdx = headers.findIndex((_, idx) => idx !== labelIdx && !isNaN(Number(data[0]?.[idx])))
  }

  const items = data.map((r) => ({
    label: String(r[labelIdx] ?? '').slice(0, 10),
    actual: actualIdx !== -1 ? Math.max(0, parseFloat(r[actualIdx]) || 0) : 0,
    theo: theoIdx !== -1 ? Math.max(0, parseFloat(r[theoIdx]) || 0) : 0,
  }))

  const maxVal = Math.max(1, ...items.map((i) => Math.max(i.actual, i.theo)))
  const chartHeight = 160
  const barWidth = items.length > 8 ? 14 : 22
  const groupGap = items.length > 8 ? 20 : 36
  const chartWidth = Math.max(340, items.length * (barWidth * 2 + groupGap) + 50)

  return (
    <div className="chart-wrapper">
      <div className="chart-legend">
        {actualIdx !== -1 && <span className="legend-item"><span className="legend-box actual" /> Actual</span>}
        {theoIdx !== -1 && <span className="legend-item"><span className="legend-box theo" /> Theoretical</span>}
      </div>
      <div className="chart-scroll">
        <svg viewBox={`0 0 ${chartWidth} ${chartHeight + 45}`} className="chart-svg" style={{ minWidth: chartWidth }}>
          <line x1="20" y1={chartHeight} x2={chartWidth} y2={chartHeight} stroke="#cbd5e1" strokeWidth="1" />
          {items.map((item, i) => {
            const x = 30 + i * (barWidth * 2 + groupGap)
            const hActual = (item.actual / maxVal) * (chartHeight - 30)
            const hTheo = (item.theo / maxVal) * (chartHeight - 30)
            return (
              <g key={i}>
                {theoIdx !== -1 && (
                  <>
                    <rect x={x} y={chartHeight - hTheo} width={barWidth} height={hTheo} rx="3" fill="#f59e0b" />
                    {hTheo > 18 && (
                      <text x={x + barWidth / 2} y={chartHeight - hTheo - 4} fontSize="9" textAnchor="middle" fill="#78350f">
                        {Math.round(item.theo)}
                      </text>
                    )}
                  </>
                )}
                {actualIdx !== -1 && (
                  <>
                    <rect x={theoIdx !== -1 ? x + barWidth + 2 : x} y={chartHeight - hActual} width={barWidth} height={hActual} rx="3" fill="#3b82f6" />
                    {hActual > 18 && (
                      <text x={(theoIdx !== -1 ? x + barWidth + 2 : x) + barWidth / 2} y={chartHeight - hActual - 4} fontSize="9" textAnchor="middle" fill="#1e3a8a">
                        {Math.round(item.actual)}
                      </text>
                    )}
                  </>
                )}
                <text x={x + barWidth} y={chartHeight + 16} fontSize="10" textAnchor="middle" fill="#475569">
                  {item.label}
                </text>
              </g>
            )
          })}
        </svg>
      </div>
    </div>
  )
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
  const [uploading, setUploading] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editingTitle, setEditingTitle] = useState('')
  const [chartViews, setChartViews] = useState<Record<number, boolean>>({})
  const bottomRef = useRef<HTMLDivElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

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

  async function handleFileUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    const formData = new FormData()
    formData.append('file', file)
    try {
      const res = await fetch(`${API_BASE}/api/upload`, {
        method: 'POST',
        headers: { 'X-API-Key': localStorage.getItem('tunnel-api-key') || DEFAULT_API_KEY },
        body: formData,
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Upload failed')
      alert(`Success! Imported ${data.imported} records (Total in DB: ${data.total_records})`)
      await loadConversations()
    } catch (err: any) {
      alert(`Upload error: ${err.message}`)
    } finally {
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  function toggleChart(msgIdx: number) {
    setChartViews((prev) => ({ ...prev, [msgIdx]: !prev[msgIdx] }))
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
      setMessages((items) => [
        ...items,
        {
          role: 'assistant',
          content: cleanAnswer(data.answer),
          rows: data.table ?? [],
          generated_query: data.generated_query,
        },
      ])
      await loadConversations()
    } catch {
      setMessages((items) => [
        ...items,
        { role: 'assistant', content: 'I could not connect to the backend. Please start the FastAPI server.', rows: [] },
      ])
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="app-shell">
      <button className="menu-button" onClick={() => setSidebarOpen(!sidebarOpen)} aria-label="Toggle conversations">☰</button>
      <aside className={`sidebar ${sidebarOpen ? 'sidebar-open' : ''}`}>
        <div className="sidebar-head">
          <span>Conversations</span>
          <button className="new-button" onClick={newChat}>+ New chat</button>
        </div>

        <div className="sidebar-upload">
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv,.xlsx,.xls"
            onChange={handleFileUpload}
            style={{ display: 'none' }}
            id="file-upload-input"
          />
          <label htmlFor="file-upload-input" className={`upload-action-btn ${uploading ? 'uploading' : ''}`}>
            {uploading ? '⏳ Uploading...' : '📁 Upload Excel/CSV Data'}
          </label>
        </div>

        <div className="conversation-list">
          {conversations.map((item) => (
            <div className={`conversation-item ${activeId === item.id ? 'active' : ''}`} key={item.id}>
              {editingId === item.id ? (
                <input
                  autoFocus
                  value={editingTitle}
                  onChange={(event) => setEditingTitle(event.target.value)}
                  onKeyDown={(event) => { if (event.key === 'Enter') void renameConversation(item.id) }}
                  onBlur={() => void renameConversation(item.id)}
                />
              ) : (
                <button className="conversation-select" onClick={() => selectConversation(item.id)}>{item.title}</button>
              )}
              <div className="conversation-actions">
                <button onClick={() => { setEditingId(item.id); setEditingTitle(item.title) }} aria-label="Rename">✎</button>
                <button onClick={() => void deleteConversation(item.id)} aria-label="Delete">×</button>
              </div>
            </div>
          ))}
        </div>
      </aside>

      <section className="chat-panel">
        <header>
          <h1>Tunnel Excavation AI</h1>
          <p>Ask about excavation data or chat normally.</p>
        </header>

        <div className="messages" aria-live="polite">
          {messages.length === 0 && <div className="empty-state">Start a new conversation.</div>}
          {messages.map((message, index) => (
            <div className={`message-row ${message.role}`} key={`${message.created_at ?? 'new'}-${index}`}>
              <div className="bubble">
                {cleanAnswer(message.content)}

                {message.generated_query && (
                  <details className="sql-details">
                    <summary className="sql-summary">🔍 View Executed SQL Query</summary>
                    <pre className="sql-block"><code>{message.generated_query}</code></pre>
                  </details>
                )}

                {message.rows && message.rows.length > 0 && (
                  <div className="table-wrapper-box">
                    <div className="table-toolbar">
                      <span className="record-badge">{message.rows.length - 1} records</span>
                      <div className="toolbar-buttons">
                        {message.rows.length > 2 && (
                          <button className="btn-secondary" onClick={() => toggleChart(index)}>
                            {chartViews[index] ? '📋 View Table' : '📊 View Chart'}
                          </button>
                        )}
                        <button className="btn-secondary" onClick={() => exportToCsv(message.rows!)}>
                          📥 Export CSV
                        </button>
                      </div>
                    </div>

                    {chartViews[index] ? (
                      <SvgChart rows={message.rows} />
                    ) : (
                      <div className="table-wrap">
                        <table>
                          <thead>
                            <tr>
                              {message.rows[0].map((cell) => <th key={cell}>{cell}</th>)}
                            </tr>
                          </thead>
                          <tbody>
                            {message.rows.slice(1).map((row, rowIndex) => (
                              <tr key={rowIndex}>
                                {row.map((cell, cellIndex) => (
                                  <td key={`${rowIndex}-${cellIndex}`}>{cell}</td>
                                ))}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          ))}
          {loading && <div className="message-row assistant"><div className="bubble thinking">Thinking...</div></div>}
          <div ref={bottomRef} />
        </div>

        <div className="composer">
          <input
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            onKeyDown={(event) => { if (event.key === 'Enter') void ask() }}
            placeholder="Ask about excavation (e.g. actual excavation on 12-01-2025)..."
            aria-label="Question"
          />
          <button onClick={() => void ask()} disabled={loading || !question.trim()}>
            {loading ? 'Thinking...' : 'Ask'}
          </button>
        </div>
      </section>
    </main>
  )
}

createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>)
