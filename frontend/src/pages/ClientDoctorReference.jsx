import { useCallback, useEffect, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import api from '../api'
import Breadcrumbs from '../components/Breadcrumbs'
import DoctorReferenceFields from '../components/client-profile/DoctorReferenceFields'
import DoctorReferenceSections from '../components/client-profile/DoctorReferenceSections'
import ProfileTabs from '../components/client-profile/ProfileTabs'
import { isDefaultPreferenceSection, newProfileId } from '../components/client-profile/profileUtils'
import { useAuth } from '../context/AuthContext'
import { useUI } from '../context/UIContext'

export default function ClientDoctorReference() {
  const { client, clientId } = useOutletContext()
  const { token } = useAuth()
  const { toast } = useUI()

  const [sections, setSections] = useState([])
  const [editors, setEditors] = useState([])
  const [activeId, setActiveId] = useState(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  const activeSection = sections.find((section) => section.id === activeId) || sections[0] || null

  const persist = useCallback(
    async (nextSections) => {
      if (!token || !clientId) return
      setSaving(true)
      try {
        const data = await api.saveDoctorReference(token, clientId, nextSections)
        const saved = data?.reference?.sections || nextSections
        setSections(saved)
        return saved
      } catch (err) {
        toast(err.message, 'error')
        return null
      } finally {
        setSaving(false)
      }
    },
    [token, clientId, toast],
  )

  useEffect(() => {
    if (!token || !clientId) return
    let cancelled = false
    ;(async () => {
      setLoading(true)
      try {
        const [data, meta] = await Promise.all([
          api.getDoctorReference(token, clientId),
          api.getEditTrackerMeta(token).catch(() => ({ editors: [] })),
        ])
        if (cancelled) return
        const next = (data?.reference?.sections || []).map((section) => ({
          ...section,
          is_default: isDefaultPreferenceSection(section),
        }))
        setEditors(meta.editors || [])
        setSections(next)
        setActiveId(next[0]?.id || null)
      } catch (err) {
        if (!cancelled) toast(err.message, 'error')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [token, clientId, toast])

  function patchSections(mutator) {
    const next = mutator(sections.map((section) => ({
      ...section,
      fields: [...(section.fields || [])],
    })))
    setSections(next)
    persist(next)
    return next
  }

  function handleSaveField(updated) {
    patchSections((current) =>
      current.map((section) => {
        if (section.id !== activeSection?.id) return section
        return {
          ...section,
          fields: (section.fields || []).map((field) =>
            field.id === updated.id ? { ...field, label: updated.label, value: updated.value } : field,
          ),
        }
      }),
    )
  }

  function handleDeleteField(fieldId) {
    patchSections((current) =>
      current.map((section) => {
        if (section.id !== activeSection?.id) return section
        return {
          ...section,
          fields: (section.fields || []).filter((field) => field.id !== fieldId),
        }
      }),
    )
  }

  function handleAddField(label) {
    if (!activeSection) return
    patchSections((current) =>
      current.map((section) => {
        if (section.id !== activeSection.id) return section
        return {
          ...section,
          fields: [
            ...(section.fields || []),
            { id: newProfileId('fld'), label, value: '' },
          ],
        }
      }),
    )
  }

  async function handleAddSection(title) {
    const section = {
      id: newProfileId('sec'),
      title,
      is_default: false,
      fields: [],
    }
    const next = [...sections, section]
    setSections(next)
    setActiveId(section.id)
    await persist(next)
  }

  async function handleDeleteSection(targetId) {
    const next = sections.filter(
      (section) => section.id !== targetId || isDefaultPreferenceSection(section),
    )
    setSections(next)
    if (activeId === targetId) {
      setActiveId(next[0]?.id || null)
    }
    await persist(next)
  }

  return (
    <>
      <ProfileTabs clientId={clientId} />

      <header className="content-header">
        <div className="greeting">
          <Breadcrumbs
            items={[
              { label: 'Clients', to: '/clients' },
              { label: client?.name || 'Client', to: `/clients/${clientId}` },
              { label: 'Preferences and behaviour' },
            ]}
          />
          <h1>Preferences and behaviour</h1>
          <p>Production notes and working preferences for this client, grouped by section.</p>
        </div>
        {saving && <span className="text-muted">Saving…</span>}
      </header>

      {loading ? (
        <p className="text-muted">Loading preferences…</p>
      ) : (
        <div className="doctor-ref-layout">
          <DoctorReferenceSections
            sections={sections}
            activeId={activeSection?.id}
            onSelect={setActiveId}
            onAddSection={handleAddSection}
            onDeleteSection={handleDeleteSection}
          />
          {activeSection ? (
            <DoctorReferenceFields
              section={activeSection}
              editors={editors}
              onSaveField={handleSaveField}
              onDeleteField={handleDeleteField}
              onAddField={handleAddField}
            />
          ) : (
            <div className="doctor-ref-fields card">
              <p className="text-muted">Add a section to get started.</p>
            </div>
          )}
        </div>
      )}
    </>
  )
}
