import { useCallback, useEffect, useRef, useState } from 'react'
import DelayProofModal from './DelayProofModal'
import TrackerCard from './TrackerCard'
import {
  ADDABLE_CARD_TYPES,
  allowedCardTypes,
  cardsSummary,
  calendarWeekDates,
  defaultEditHours,
  displayLanguages,
  applyCardHistory,
  emptyCard,
  isVideoCard,
  maybeAdvanceStage,
  needsDelayProof,
  seedDestinations,
  serializableCard,
  sortCardsByType,
  startCard,
} from './trackerUtils'
import api from '../../api'
import { useAuth } from '../../context/AuthContext'
import { useUI } from '../../context/UIContext'

export default function TrackerWeekBoard({ clientId, client, year, month, week, focusCardId = '', onSummaryChange }) {
  const { token, user } = useAuth()
  const actor = user?.username || ''
  const { toast } = useUI()
  const [cards, setCards] = useState([])
  const [weekSlots, setWeekSlots] = useState(null)
  const [languages, setLanguages] = useState([])
  const [loading, setLoading] = useState(true)
  const [scriptedItems, setScriptedItems] = useState([])
  const [planItems, setPlanItems] = useState([])
  const [planKeywords, setPlanKeywords] = useState([])
  const [scriptBusyId, setScriptBusyId] = useState(null)
  const [channels, setChannels] = useState([])
  const [editors, setEditors] = useState([])
  const [delayGate, setDelayGate] = useState(null)
  const saveTimer = useRef(null)
  const skipNextSave = useRef(true)
  const loadedKey = useRef('')
  const onSummaryChangeRef = useRef(onSummaryChange)
  onSummaryChangeRef.current = onSummaryChange

  const loadWeek = useCallback(async (nextClientId, nextYear, nextMonth, nextWeek) => {
    if (!token || !nextClientId) return
    setLoading(true)
    try {
      const result = await api.getWeeklyTracker(token, nextClientId, nextYear, nextMonth, nextWeek)
      loadedKey.current = `${nextClientId}-${nextYear}-${nextMonth}-${nextWeek}`
      skipNextSave.current = true
      const langs = displayLanguages(result.languages || [])
      const nextCards = (result.tracker?.cards || []).map((card) => {
        let next = {
          ...card,
          started: true,
          collapsed: !focusCardId || String(card.id) !== String(focusCardId),
        }
        if (!(next.destinations || []).length) {
          next = { ...next, destinations: seedDestinations(next, langs) }
        }
        return next
      })
      setCards(nextCards)
      setWeekSlots(result.tracker?.deliverable_slots || null)
      setLanguages(langs)
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setLoading(false)
    }
  }, [token, toast, focusCardId])

  const loadScripts = useCallback(async (nextClientId) => {
    if (!token || !nextClientId) return
    try {
      const data = await api.getContentPlan(token, nextClientId)
      const items = data.suggestions?.items || []
      setPlanItems(items)
      setPlanKeywords(data.suggestions?.keyword_analysis || [])
      setScriptedItems(items.filter((item) => (item.script || '').trim()))
    } catch (err) {
      toast(err.message, 'error')
    }
  }, [token, toast])

  const loadChannels = useCallback(async (nextClientId) => {
    if (!token || !nextClientId) return
    try {
      const data = await api.listChannels(token, nextClientId)
      setChannels(data.channels || [])
    } catch (err) {
      toast(err.message, 'error')
    }
  }, [token, toast])

  useEffect(() => {
    loadWeek(clientId, year, month, week)
  }, [clientId, year, month, week, loadWeek])

  useEffect(() => {
    loadScripts(clientId)
    loadChannels(clientId)
  }, [clientId, loadScripts, loadChannels])

  useEffect(() => {
    if (!token) return
    let cancelled = false
    api.getEditTrackerMeta(token).then((data) => {
      if (!cancelled) setEditors(data.editors || [])
    }).catch(() => {
      if (!cancelled) setEditors([])
    })
    return () => {
      cancelled = true
    }
  }, [token])

  const persist = useCallback((nextCards, { immediate } = {}) => {
    if (!token || !clientId) return
    const key = `${clientId}-${year}-${month}-${week}`
    if (loadedKey.current !== key) return
    clearTimeout(saveTimer.current)
    const run = async () => {
      if (loadedKey.current !== key) return
      try {
        await api.saveWeeklyTracker(
          token,
          clientId,
          year,
          month,
          week,
          nextCards.map(serializableCard),
        )
      } catch (err) {
        toast(err.message, 'error')
      }
    }
    if (immediate) {
      run()
      return
    }
    saveTimer.current = setTimeout(run, 400)
  }, [token, clientId, year, month, week, toast])

  useEffect(() => {
    if (skipNextSave.current) {
      skipNextSave.current = false
      return
    }
    persist(cards)
  }, [cards, persist])

  useEffect(() => {
    if (loading || !onSummaryChangeRef.current) return
    const summary = cardsSummary(cards)
    onSummaryChangeRef.current(clientId, week, {
      week,
      out: summary.out,
      total: summary.total,
      to_start: summary.toStart,
    })
  }, [cards, week, loading, clientId, client])

  useEffect(() => () => clearTimeout(saveTimer.current), [])

  function applyWeekUpdate(result) {
    const nextCards = result.tracker?.cards || []
    const newlyComplete = nextCards.find((next) => {
      const previous = cards.find((card) => card.id === next.id)
      return needsDelayProof(previous, next, year, month, week)
    })
    skipNextSave.current = true
    setCards(nextCards)
    if (result.tracker?.deliverable_slots) setWeekSlots(result.tracker.deliverable_slots)
    if (result.languages) setLanguages(result.languages)
    if (newlyComplete) setDelayGate({ next: newlyComplete })
  }

  function patchCard(nextCard) {
    const current = cards.find((card) => card.id === nextCard.id)
    if (needsDelayProof(current, nextCard, year, month, week)) {
      setDelayGate({ next: nextCard })
      return
    }
    setCards((prev) => prev.map((card) => (
      card.id === nextCard.id ? applyCardHistory(card, nextCard, actor) : card
    )))
  }

  function applyDelayProof({ reason, proofs }) {
    const pending = delayGate?.next
    if (!pending) return
    const current = cards.find((card) => card.id === pending.id)
    setDelayGate(null)
    setCards((prev) => prev.map((card) => (
      card.id === pending.id
        ? applyCardHistory(current || card, {
            ...pending,
            delay_reason: reason,
            delay_proofs: proofs,
            delay_recorded_at: new Date().toISOString(),
          }, actor)
        : card
    )))
  }

  function addCard(type) {
    setCards((prev) => {
      const card = startCard(emptyCard(type, prev.length, false), languages)
      if (isVideoCard(type)) {
        card.editor_id = client?.video_editor_id || editors[0]?.id || ''
        card.edit_hours = defaultEditHours(client, type)
      }
      return sortCardsByType([...prev, applyCardHistory(null, { ...card, collapsed: true }, actor)])
    })
  }

  function deleteCard(cardId) {
    setCards((prev) => {
      const next = prev.filter((card) => card.id !== cardId)
      skipNextSave.current = true
      persist(next, { immediate: true })
      return next
    })
  }

  const deliverables = allowedCardTypes(weekSlots || client?.tracker_deliverables)
  const visibleCards = sortCardsByType(cards)

  const weekContext = {
    token,
    clientId,
    year,
    month,
    week,
    toast,
    clientName: client?.name || '',
    channels,
    editors,
    weekDates: calendarWeekDates(),
    onWeekUpdate: applyWeekUpdate,
    reloadWeek: async () => {
      if (!token || !clientId) return null
      const result = await api.getWeeklyTracker(token, clientId, year, month, week)
      applyWeekUpdate(result)
      return result
    },
  }

  async function handlePickScript(card, item) {
    if (!token || !clientId || !item?.id) return
    setScriptBusyId(card.id)
    try {
      const result = await api.attachTrackerScript(token, clientId, {
        itemId: item.id,
        year,
        month,
        week,
        cardId: card.id,
      })
      applyWeekUpdate(result)
      if (result.status === 'already') {
        toast('Already on this card', 'info')
      } else if (card.content_plan_item_id && card.content_plan_item_id !== item.id) {
        toast('Script changed', 'success')
      } else {
        toast('Script added to this card', 'success')
      }
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setScriptBusyId(null)
    }
  }

  async function handleSaveScriptText(card, text) {
    if (!token || !clientId) return
    const manual = card.assets?.script_source === 'manual'
    setScriptBusyId(card.id)
    try {
      if (!manual && card.content_plan_item_id) {
        await api.updateContentScript(token, clientId, {
          itemId: card.content_plan_item_id,
          script: text,
        })
        skipNextSave.current = true
        setCards((prev) => prev.map((row) => {
          if (row.content_plan_item_id !== card.content_plan_item_id) return row
          if (row.id !== card.id && row.assets?.script_source === 'manual') return row
          return {
            ...row,
            assets: { ...(row.assets || {}), script_text: text, script_url: '', script_source: 'plan' },
          }
        }))
        await loadScripts(clientId)
        toast('Script updated in tracker and content plan', 'success')
      } else {
        patchCard(maybeAdvanceStage({
          ...card,
          started: true,
          assets: { ...(card.assets || {}), script_text: text, script_url: '', script_source: manual ? 'manual' : (card.assets?.script_source || '') },
        }))
        toast('Script saved on this card', 'success')
      }
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setScriptBusyId(null)
    }
  }

  function handleSaveManualScript(card, payload) {
    const text = typeof payload === 'string' ? payload : payload?.text
    const nextTitle = typeof payload === 'string' ? card.title : (payload?.title || '')
    patchCard(maybeAdvanceStage({
      ...card,
      started: true,
      collapsed: false,
      title: nextTitle || card.title || '',
      topic_id: typeof payload === 'string' ? card.topic_id : (payload?.topicId || null),
      content_plan_item_id: typeof payload === 'string' ? card.content_plan_item_id : (payload?.itemId || null),
      assets: {
        ...(card.assets || {}),
        script_text: text,
        script_url: '',
        script_source: 'manual',
      },
    }))
    toast('Script saved on this card', 'success')
  }

  function titlesForCard(card) {
    const wantShort = card.type === 'short'
    const matches = (format) => (wantShort ? format === 'Short' : format !== 'Short')
    const rows = planItems.filter((item) => item?.id && matches(item.format)).map((item) => ({
      key: item.id,
      title: item.title_hinglish || item.working_title || item.title_en || item.topic_text || 'Untitled',
      keyword: item.topic_text || '',
      itemId: item.id,
      topicId: item.topic_id || null,
    }))
    const covered = new Set(rows.map((row) => row.topicId).filter(Boolean))
    planKeywords.forEach((keyword) => {
      if (!keyword?.topic_id || covered.has(keyword.topic_id)) return
      rows.push({
        key: `kw:${keyword.topic_id}`,
        title: keyword.topic_text || 'Untitled',
        keyword: keyword.topic_text || '',
        itemId: null,
        topicId: keyword.topic_id,
      })
    })
    return rows
  }

  if (loading) {
    return <p className="text-muted" style={{ padding: '16px 0' }}>Loading week…</p>
  }

  return (
    <div className="tracker-week-board">
      {!visibleCards.length ? (
        <p className="text-muted">
          {deliverables.length
            ? 'No tracker cards for this week yet.'
            : 'No deliverables selected for this client. Set them in Client Profile → Deliverables.'}
        </p>
      ) : null}
      <div className="tracker-card-stack">
        {visibleCards.map((card) => (
          <TrackerCard
            key={card.id}
            card={card}
            languages={displayLanguages(languages)}
            weekContext={weekContext}
            scriptedItems={scriptedItems.filter((item) => (
              card.type === 'short' ? item.format === 'Short' : item.format !== 'Short'
            ))}
            titleOptions={titlesForCard(card)}
            scriptBusy={scriptBusyId === card.id}
            onPickScript={(item) => handlePickScript(card, item)}
            onSaveScriptText={(text) => handleSaveScriptText(card, text)}
            onSaveManualScript={(text) => handleSaveManualScript(card, text)}
            onChange={patchCard}
            onDelete={() => deleteCard(card.id)}
          />
        ))}
      </div>
      <div className="tracker-add-cards">
        {ADDABLE_CARD_TYPES.map((row) => (
          <button
            key={row.type}
            type="button"
            className="tracker-add-card"
            onClick={() => addCard(row.type)}
          >
            <i className="fa-solid fa-plus" />
            {row.label}
          </button>
        ))}
      </div>
      {delayGate?.next ? (
        <DelayProofModal
          token={token}
          uploadFields={{
            clientId,
            year,
            month,
            week,
            cardId: delayGate.next.id,
          }}
          onCancel={() => setDelayGate(null)}
          onSubmit={applyDelayProof}
        />
      ) : null}
    </div>
  )
}
