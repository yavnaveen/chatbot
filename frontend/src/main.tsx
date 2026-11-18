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

function toSortableDate(d: string): string {
  const match = d.match(/^(\d{1,2})-(\d{1,2})-(\d{4})$/)
  if (match) return `${match[3]}-${match[2].padStart(2, '0')}-${match[1].padStart(2, '0')}`
  return d
}

function formatLabel(val: string): string {
  const match = val.match(/^(\d{1,2})-(\d{1,2})-(\d{4})$/)
  if (match) {
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    const mIdx = parseInt(match[2], 10) - 1
    return `${match[1]} ${months[mIdx] || match[2]}`
  }
  return val
}

function SvgChart({ rows }: { rows: string[][] }) {
  if (!rows || rows.length < 2) return null
  const headers = rows[0]

  let labelIdx = headers.findIndex((h) => /date|tarikh|class|support/i.test(h))
  if (labelIdx === -1) labelIdx = 0

  let actualIdx = headers.findIndex((h) => /actual/i.test(h))
  let theoIdx = headers.findIndex((h) => /theo/i.test(h))
  if (actualIdx === -1 && theoIdx === -1) {
    actualIdx = headers.findIndex((_, idx) => idx !== labelIdx && !isNaN(Number(rows[1]?.[idx])))
  }

  // Sort rows chronologically if label is date
  const isDateColumn = /date|tarikh/i.test(headers[labelIdx])
  const sortedRaw = [...rows.slice(1)].sort((a, b) => {
    if (isDateColumn) {
      return toSortableDate(a[labelIdx] ?? '').localeCompare(toSortableDate(b[labelIdx] ?? ''))
    }
    return 0
  })

  const [rangeMode, setRangeMode] = useState<'first14' | 'latest14' | 'all'>('first14')

  const displayedRows =
    rangeMode === 'latest14'
      ? sortedRaw.slice(-14)
      : rangeMode === 'first14'
      ? sortedRaw.slice(0, 14)
      : sortedRaw

  const items = displayedRows.map((r) => ({
    fullLabel: String(r[labelIdx] ?? ''),
    displayLabel: formatLabel(String(r[labelIdx] ?? '')),
    actual: actualIdx !== -1 ? Math.max(0, parseFloat(r[actualIdx]) || 0) : 0,
    theo: theoIdx !== -1 ? Math.max(0, parseFloat(r[theoIdx]) || 0) : 0,
  }))

  const maxVal = Math.max(1, ...items.map((i) => Math.max(i.actual, i.theo)))
  const chartHeight = 180
  const barWidth = items.length > 25 ? 12 : items.length > 15 ? 16 : 22
  const groupGap = items.length > 25 ? 14 : items.length > 15 ? 20 : 32
  const slotWidth = barWidth * 2 + groupGap
  const chartWidth = Math.max(480, items.length * slotWidth + 60)

  return (
    <div className="chart-wrapper">
      <div className="chart-header-bar">
        <div className="chart-legend">
          {actualIdx !== -1 && <span className="legend-item"><span className="legend-box actual" /> Actual (m³)</span>}
          {theoIdx !== -1 && <span className="legend-item"><span className="legend-box theo" /> Theoretical (m³)</span>}
        </div>
        {sortedRaw.length > 14 && (
          <div className="chart-range-picker">
            <button className={`range-tab ${rangeMode === 'first14' ? 'active' : ''}`} onClick={() => setRangeMode('first14')}>
              First 14
            </button>
            <button className={`range-tab ${rangeMode === 'latest14' ? 'active' : ''}`} onClick={() => setRangeMode('latest14')}>
              Latest 14
            </button>
            <button className={`range-tab ${rangeMode === 'all' ? 'active' : ''}`} onClick={() => setRangeMode('all')}>
              All ({sortedRaw.length})
            </button>
          </div>
        )}
      </div>

      <div className="chart-scroll">
        <svg viewBox={`0 0 ${chartWidth} ${chartHeight + 55}`} className="chart-svg" style={{ minWidth: chartWidth, width: rangeMode === 'all' ? chartWidth : '100%' }}>
          {/* Baseline grid */}
          <line x1="15" y1={chartHeight} x2={chartWidth - 10} y2={chartHeight} stroke="#cbd5e1" strokeWidth="1.5" />

          {items.map((item, i) => {
            const x = 30 + i * slotWidth
            const hActual = (item.actual / maxVal) * (chartHeight - 40)
            const hTheo = (item.theo / maxVal) * (chartHeight - 40)
            return (
              <g key={i}>
                {theoIdx !== -1 && (
                  <>
                    <rect x={x} y={chartHeight - hTheo} width={barWidth} height={hTheo} rx="3" fill="#f59e0b" />
                    {item.theo > 0 && (
                      <text x={x + barWidth / 2} y={chartHeight - hTheo - 4} fontSize="9" fontWeight="600" textAnchor="middle" fill="#92400e">
                        {Math.round(item.theo)}
                      </text>
                    )}
                  </>
                )}
                {actualIdx !== -1 && (
                  <>
                    <rect x={theoIdx !== -1 ? x + barWidth + 2 : x} y={chartHeight - hActual} width={barWidth} height={hActual} rx="3" fill="#3b82f6" />
                    {item.actual > 0 && (
                      <text x={(theoIdx !== -1 ? x + barWidth + 2 : x) + barWidth / 2} y={chartHeight - hActual - 4} fontSize="9" fontWeight="600" textAnchor="middle" fill="#1e40af">
                        {Math.round(item.actual)}
                      </text>
                    )}
                  </>
                )}
                {/* Clean non-colliding formatted label */}
                <text x={x + barWidth} y={chartHeight + 18} fontSize="10" fontWeight="500" textAnchor="middle" fill="#334155">
                  {item.displayLabel}
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
    if (activeId && !data.some((item) => item.id === activeId)) {
      setActiveId(null)
      localStorage.removeItem('tunnel-active-conversation')
      setMessages([])
    } else if (activeId && data.some((item) => item.id === activeId)) {
      await loadMessages(activeId)
    }
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
      let response = await fetch(`${API_BASE}/api/chat`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({ question: text, ...(activeId ? { conversation_id: activeId } : {}) }),
      })
      if (response.status === 404 && activeId) {
        // Stale conversation from previous database reset; auto-heal and create fresh chat
        setActiveId(null)
        localStorage.removeItem('tunnel-active-conversation')
        response = await fetch(`${API_BASE}/api/chat`, {
          method: 'POST',
          headers: getHeaders(),
          body: JSON.stringify({ question: text }),
        })
      }
      if (!response.ok) throw new Error('Backend error')
      const data: ChatResponse = await response.json()
      setActiveId(data.conversation_id)
      localStorage.setItem('tunnel-active-conversation', String(data.conversation_id))
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
