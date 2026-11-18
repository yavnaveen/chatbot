import { StrictMode, useEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'

type Conversation = { id: number; title: string; updated_at?: string }
type ChatMessage = {
  role: 'user' | 'assistant'
  content: string
  rows?: string[][]
  all_rows?: string[][]
  assumptions?: string[]
  can_show_rows?: boolean
  generated_query?: string | null
  created_at?: string
}
type ChatResponse = {
  success: boolean
  answer: string
  table?: string[][] | null
  all_rows?: string[][] | null
  assumptions?: string[]
  can_show_rows?: boolean
  conversation_id: number
  generated_query?: string | null
}

const API_BASE = ''
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

function extractStats(text: string) {
  const m = text.match(/Theoretical(?:\s+excavation)?(?:\s+was|:)?\s*([0-9.]+)[^,]*,\s*Actual(?:\s+excavation)?(?:\s+was|:)?\s*([0-9.]+)[^,]*,\s*(?:Difference[^(]*\([^)]*\):?|so actual minus theoretical was)\s*([+-]?[0-9.]+)/i)
  if (m) {
    const theo = m[1]
    const actual = m[2]
    let diff = m[3]
    if (!diff.startsWith('+') && !diff.startsWith('-') && !diff.startsWith('−')) {
      const num = parseFloat(diff)
      if (num > 0) diff = `+${diff}`
    }
    return { theoretical: theo, actual, diff }
  }
  return null
}

function getCellClass(cell: string, colHeader?: string): string {
  const isDiffCol = /diff|difference/i.test(colHeader || '')
  const trimmed = String(cell ?? '').trim()
  if (isDiffCol || trimmed.startsWith('+') || trimmed.startsWith('-') || trimmed.startsWith('−')) {
    if (trimmed.startsWith('+') || (isDiffCol && parseFloat(trimmed) > 0)) {
      return 'up'
    }
    if (trimmed.startsWith('-') || trimmed.startsWith('−') || (isDiffCol && parseFloat(trimmed) < 0)) {
      return 'dn'
    }
  }
  return ''
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

  const labels = displayedRows.map((r) => formatLabel(r[labelIdx] ?? ''))
  const actuals = actualIdx !== -1 ? displayedRows.map((r) => parseFloat(r[actualIdx] ?? '0') || 0) : []
  const theos = theoIdx !== -1 ? displayedRows.map((r) => parseFloat(r[theoIdx] ?? '0') || 0) : []

  const maxVal = Math.max(...actuals, ...theos, 1)

  const w = 760
  const h = 260
  const p = { top: 20, right: 30, bottom: 45, left: 45 }
  const plotW = w - p.left - p.right
  const plotH = h - p.top - p.bottom
  const count = labels.length

  const getX = (i: number) => p.left + (count > 1 ? (i / (count - 1)) * plotW : plotW / 2)
  const getY = (val: number) => p.top + plotH - (val / maxVal) * plotH

  const makePath = (data: number[]) => {
    if (data.length === 0) return ''
    return data.map((v, i) => `${i === 0 ? 'M' : 'L'} ${getX(i)} ${getY(v)}`).join(' ')
  }

  const makeArea = (data: number[]) => {
    if (data.length === 0) return ''
    const line = makePath(data)
    return `${line} L ${getX(data.length - 1)} ${p.top + plotH} L ${getX(0)} ${p.top + plotH} Z`
  }

  return (
    <div className="chart-container" style={{ margin: '8px 0' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10, flexWrap: 'wrap', gap: 8 }}>
        <div style={{ display: 'flex', gap: 14, fontSize: 13, fontWeight: 500 }}>
          {actualIdx !== -1 && (
            <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{ width: 12, height: 12, background: '#0f766e', borderRadius: '50%', display: 'inline-block' }} />
              Actual Excavation
            </span>
          )}
          {theoIdx !== -1 && (
            <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{ width: 12, height: 12, background: '#f59e0b', borderRadius: '50%', display: 'inline-block' }} />
              Theoretical
            </span>
          )}
        </div>
        {sortedRaw.length > 14 && (
          <div style={{ display: 'flex', gap: 6, fontSize: 12 }}>
            <button
              className="btn"
              style={{ background: rangeMode === 'first14' ? '#e6f4f1' : '#fff', color: rangeMode === 'first14' ? '#0b5d56' : '#334155' }}
              onClick={() => setRangeMode('first14')}
            >
              First 14
            </button>
            <button
              className="btn"
              style={{ background: rangeMode === 'latest14' ? '#e6f4f1' : '#fff', color: rangeMode === 'latest14' ? '#0b5d56' : '#334155' }}
              onClick={() => setRangeMode('latest14')}
            >
              Latest 14
            </button>
            <button
              className="btn"
              style={{ background: rangeMode === 'all' ? '#e6f4f1' : '#fff', color: rangeMode === 'all' ? '#0b5d56' : '#334155' }}
              onClick={() => setRangeMode('all')}
            >
              All ({sortedRaw.length})
            </button>
          </div>
        )}
      </div>

      <div style={{ width: '100%', overflowX: 'auto' }}>
        <svg viewBox={`0 0 ${w} ${h}`} style={{ width: '100%', minWidth: 500, height: 'auto', display: 'block' }}>
          {[0, 0.25, 0.5, 0.75, 1].map((pct) => {
            const y = p.top + plotH * (1 - pct)
            const val = Math.round(maxVal * pct)
            return (
              <g key={pct}>
                <line x1={p.left} y1={y} x2={w - p.right} y2={y} stroke="#e5e9f0" strokeDasharray="3 3" />
                <text x={p.left - 8} y={y + 4} textAnchor="end" fontSize="11" fill="#94a3b8">
                  {val}
                </text>
              </g>
            )
          })}

          {theoIdx !== -1 && theos.length > 0 && (
            <>
              <path d={makeArea(theos)} fill="rgba(245, 158, 11, 0.08)" />
              <path d={makePath(theos)} fill="none" stroke="#f59e0b" strokeWidth="2.5" />
              {theos.map((v, i) => (
                <circle key={`t-${i}`} cx={getX(i)} cy={getY(v)} r="3.5" fill="#f59e0b" />
              ))}
            </>
          )}

          {actualIdx !== -1 && actuals.length > 0 && (
            <>
              <path d={makeArea(actuals)} fill="rgba(15, 118, 110, 0.09)" />
              <path d={makePath(actuals)} fill="none" stroke="#0f766e" strokeWidth="2.5" />
              {actuals.map((v, i) => (
                <circle key={`a-${i}`} cx={getX(i)} cy={getY(v)} r="4" fill="#0f766e" stroke="#fff" strokeWidth="1.5" />
              ))}
            </>
          )}

          {labels.map((lbl, i) => (
            <text
              key={`l-${i}`}
              x={getX(i)}
              y={h - 12}
              textAnchor="middle"
              fontSize={count > 20 ? '9' : '11'}
              fill="#64748b"
            >
              {lbl}
            </text>
          ))}
        </svg>
      </div>
    </div>
  )
}

export function App() {
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [activeId, setActiveId] = useState<number | null>(() => {
    const raw = localStorage.getItem('tunnel-active-conversation')
    return raw ? Number(raw) : null
  })
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [question, setQuestion] = useState('')
  const [loading, setLoading] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editingTitle, setEditingTitle] = useState('')
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [chartViews, setChartViews] = useState<Record<number, boolean>>({})
  const [expandedRecords, setExpandedRecords] = useState<Record<number, boolean>>({})
  const [rowLimits, setRowLimits] = useState<Record<number, number>>({})
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

  async function submitQuestion(textToAsk?: string) {
    const text = (textToAsk || question).trim()
    if (!text || loading) return
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
          rows: data.table && data.table.length > 0 ? data.table : undefined,
          all_rows: data.all_rows ?? data.table ?? undefined,
          assumptions: data.assumptions ?? [],
          can_show_rows: data.can_show_rows,
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
    <div className="app">
      <aside className={`side ${sidebarOpen ? 'open' : ''}`}>
        <div className="brand">
          <div className="logo">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2" aria-hidden="true">
              <path d="M3 20V12a9 9 0 0 1 18 0v8" />
              <path d="M8 20v-8a4 4 0 0 1 8 0v8" />
            </svg>
          </div>
          <span>Tunnel Excavation AI</span>
        </div>

        <button className="new" type="button" onClick={newChat}>
          + New chat
        </button>

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

        <div className="lbl">Conversations</div>

        <div className="conversation-list">
          {conversations.map((item) => (
            <div className={`row ${activeId === item.id ? 'on' : ''}`} key={item.id}>
              {editingId === item.id ? (
                <input
                  className="chat-edit-input"
                  autoFocus
                  value={editingTitle}
                  onChange={(event) => setEditingTitle(event.target.value)}
                  onKeyDown={(event) => { if (event.key === 'Enter') void renameConversation(item.id) }}
                  onBlur={() => void renameConversation(item.id)}
                />
              ) : (
                <button
                  className={`chat ${activeId === item.id ? 'on' : ''}`}
                  onClick={() => selectConversation(item.id)}
                  title={item.title}
                >
                  {item.title}
                </button>
              )}
              <div className="row-actions">
                <button
                  className="act-btn"
                  onClick={() => { setEditingId(item.id); setEditingTitle(item.title) }}
                  aria-label={`Rename chat: ${item.title}`}
                  title="Rename"
                >
                  ✎
                </button>
                <button
                  className="act-btn del-btn"
                  onClick={(e) => { e.stopPropagation(); void deleteConversation(item.id) }}
                  aria-label={`Delete chat: ${item.title}`}
                  title="Delete"
                >
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
                    <path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14M10 11v5M14 11v5" />
                  </svg>
                </button>
              </div>
            </div>
          ))}
        </div>
      </aside>

      <section className="main">
        <header className="top">
          <div className="top-left">
            <button
              className="mobile-toggle"
              onClick={() => setSidebarOpen(!sidebarOpen)}
              aria-label="Toggle conversations menu"
            >
              ☰
            </button>
            <div>
              <h1>Excavation assistant</h1>
              <p>Ask about dates, support class, chainage or theoretical vs actual excavation.</p>
            </div>
          </div>
          <span className="pill">Project data: 01-01-2025 to 28-02-2025</span>
        </header>

        <div className="feed" aria-live="polite">
          {messages.length === 0 && (
            <div className="empty-state-card">
              <div className="empty-state-icon">🚇</div>
              <h2>Tunnel Excavation Assistant</h2>
              <p>Ask about excavation dates, pull, support classes (A-F), chainage, or compare theoretical vs actual volume.</p>
            </div>
          )}

          {messages.map((message, index) => {
            if (message.role === 'user') {
              return (
                <div className="me" key={`${message.created_at ?? 'new'}-${index}`}>
                  {cleanAnswer(message.content)}
                </div>
              )
            }

            const stats = extractStats(message.content)
            const effectiveRows = (message.rows && message.rows.length > 0)
              ? message.rows
              : (expandedRecords[index] && message.all_rows && message.all_rows.length > 0)
                ? message.all_rows
                : null

            return (
              <div className="bot" key={`${message.created_at ?? 'new'}-${index}`}>
                <p>{cleanAnswer(message.content)}</p>

                {message.assumptions && message.assumptions.length > 0 && (
                  <div className="note">
                    {message.assumptions.map((item, i) => (
                      <div key={i}>{item}</div>
                    ))}
                  </div>
                )}

                {stats && (
                  <div className="stats">
                    <div className="stat">
                      <span>Theoretical</span>
                      <b>{stats.theoretical}</b>
                    </div>
                    <div className="stat">
                      <span>Actual</span>
                      <b>{stats.actual}</b>
                    </div>
                    <div className="stat">
                      <span>Difference (actual − theoretical)</span>
                      <b style={{ color: '#0f766e' }}>{stats.diff}</b>
                    </div>
                  </div>
                )}

                {!effectiveRows && message.can_show_rows && message.all_rows && message.all_rows.length > 1 && (() => {
                  const hasTot = message.all_rows[message.all_rows.length - 1][0] === 'Total'
                  const count = hasTot ? message.all_rows.length - 2 : message.all_rows.length - 1
                  return (
                    <div style={{ marginTop: '12px' }}>
                      <button
                        className="btn"
                        onClick={() => setExpandedRecords((prev) => ({ ...prev, [index]: true }))}
                      >
                        📋 Show records ({count} {count === 1 ? 'record' : 'records'})
                      </button>
                    </div>
                  )
                })()}

                {effectiveRows && (() => {
                  const header = effectiveRows[0]
                  const hasTotalRow = effectiveRows[effectiveRows.length - 1][0] === 'Total'
                  const dataRows = hasTotalRow ? effectiveRows.slice(1, -1) : effectiveRows.slice(1)
                  const totalRow = hasTotalRow ? effectiveRows[effectiveRows.length - 1] : null

                  const limit = rowLimits[index] || 20
                  const visibleDataRows = dataRows.slice(0, limit)
                  const totalCount = dataRows.length

                  return (
                    <div className="tbl">
                      <div className="bar">
                        <span>
                          {limit < totalCount
                            ? `Showing ${visibleDataRows.length} of ${totalCount} records`
                            : `${totalCount} ${totalCount === 1 ? 'record' : 'records'}`}
                        </span>
                        <div className="bar-actions">
                          {dataRows.length > 1 && (
                            <button className="btn" onClick={() => toggleChart(index)}>
                              {chartViews[index] ? '📋 View Table' : '📊 View Chart'}
                            </button>
                          )}
                          <button className="btn" onClick={() => exportToCsv(message.all_rows || effectiveRows)}>
                            📥 Export CSV
                          </button>
                        </div>
                      </div>

                      {chartViews[index] ? (
                        <div style={{ padding: '14px' }}>
                          <SvgChart rows={effectiveRows} />
                        </div>
                      ) : (
                        <div className="table-scroll">
                          <table>
                            <thead>
                              <tr>
                                {header.map((cell) => (
                                  <th key={cell}>{cell}</th>
                                ))}
                              </tr>
                            </thead>
                            <tbody>
                              {visibleDataRows.map((row, rowIndex) => (
                                <tr key={rowIndex}>
                                  {row.map((cell, cellIndex) => (
                                    <td key={`${rowIndex}-${cellIndex}`} className={getCellClass(cell, header[cellIndex])}>
                                      {cell}
                                    </td>
                                  ))}
                                </tr>
                              ))}
                              {totalRow && (
                                <tr key="total-row" style={{ fontWeight: 600, background: '#f8fafc' }}>
                                  {totalRow.map((cell, cellIndex) => (
                                    <td key={`total-${cellIndex}`} className={getCellClass(cell, header[cellIndex])}>
                                      {cell}
                                    </td>
                                  ))}
                                </tr>
                              )}
                            </tbody>
                          </table>
                        </div>
                      )}

                      {limit < totalCount && (
                        <div className="show-more-box">
                          <button
                            className="btn-show-more"
                            onClick={() => setRowLimits((prev) => ({ ...prev, [index]: (prev[index] || 20) + 20 }))}
                          >
                            ▼ Show more ({totalCount - limit} remaining)
                          </button>
                        </div>
                      )}
                    </div>
                  )
                })()}
              </div>
            )
          })}

          {loading && (
            <div className="bot">
              <p style={{ color: '#64748b' }}>Thinking...</p>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        <div className="dock">
          <div className="chips">
            <button className="chip" type="button" onClick={() => void submitQuestion('Highest excavation date')}>
              Highest excavation date
            </button>
            <button className="chip" type="button" onClick={() => void submitQuestion('Class-wise totals')}>
              Class-wise totals
            </button>
            <button className="chip" type="button" onClick={() => void submitQuestion('Compare theoretical vs actual')}>
              Compare theoretical vs actual
            </button>
          </div>

          <div className="input">
            <input
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              onKeyDown={(event) => { if (event.key === 'Enter') void submitQuestion() }}
              placeholder="Ask about excavation, e.g. actual excavation on 12-01-2025"
              aria-label="Ask a question"
            />
            <button
              className="send"
              type="button"
              onClick={() => void submitQuestion()}
              disabled={loading || !question.trim()}
            >
              Ask
            </button>
          </div>
        </div>
      </section>
    </div>
  )
}

createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>)
