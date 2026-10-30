import { useEffect, useState } from 'react'
import { useUI } from '../../context/UIContext'
import plugApi from '../api'
import { usePlugAuth } from '../AuthContext'
import PlugPageHeader from '../components/PlugPageHeader'

export default function PlugProfile() {
  const { token, creator, patchCreator } = usePlugAuth()
  const { toast } = useUI()

  const [name, setName] = useState('')
  const [website, setWebsite] = useState('')
  const [instagram, setInstagram] = useState('')
  const [niche, setNiche] = useState('')
  const [nicheDetails, setNicheDetails] = useState('')
  const [exampleTopics, setExampleTopics] = useState([])
  const [topicDraft, setTopicDraft] = useState('')
  const [exampleScripts, setExampleScripts] = useState([''])
  const [referenceVideos, setReferenceVideos] = useState([])
  const [videoDraft, setVideoDraft] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!creator) return
    setName(creator.name || '')
    setWebsite(creator.website || '')
    setInstagram(creator.instagram || '')
    setNiche(creator.niche || '')
    setNicheDetails(creator.niche_details || '')
    setExampleTopics(Array.isArray(creator.example_topics) ? [...creator.example_topics] : [])
    const scripts = Array.isArray(creator.example_scripts) ? [...creator.example_scripts] : []
    setExampleScripts(scripts.length ? scripts : [''])
    setReferenceVideos(Array.isArray(creator.reference_videos) ? [...creator.reference_videos] : [])
  }, [creator?.username, creator?.updated_at])

  function addTopic(e) {
    e?.preventDefault()
    const text = topicDraft.trim()
    if (!text) return
    if (exampleTopics.some((t) => t.toLowerCase() === text.toLowerCase())) {
      setTopicDraft('')
      return
    }
    setExampleTopics((prev) => [...prev, text])
    setTopicDraft('')
  }

  function removeTopic(index) {
    setExampleTopics((prev) => prev.filter((_, i) => i !== index))
  }

  async function handleSave(e) {
    e.preventDefault()
    setSaving(true)
    try {
      const updated = await plugApi.updateProfile(token, {
        name: name.trim(),
        website: website.trim(),
        instagram: instagram.trim(),
        niche: niche.trim(),
        niche_details: nicheDetails.trim(),
        example_topics: exampleTopics.map((t) => t.trim()).filter(Boolean),
        example_scripts: exampleScripts.map((s) => s.trim()).filter(Boolean),
        reference_videos: referenceVideos.map((v) => v.trim()).filter(Boolean),
      })
      patchCreator(updated)
      toast('Profile saved', 'success')
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="plug-page animate-fade-in">
      <PlugPageHeader
        kicker="Introduction"
        title="Profile"
        subtitle="Tell us who you are as a creator. Topics and scripts use this, not a client list."
      />

      <form className="card plug-section plug-panel" onSubmit={handleSave}>
        <h2 className="plug-section-title">Basics</h2>
        <div className="plug-grid-2">
          <div className="input-group">
            <label htmlFor="plug-name">Name</label>
            <input
              id="plug-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Your name or brand"
            />
          </div>
          <div className="input-group">
            <label htmlFor="plug-website">Website</label>
            <input
              id="plug-website"
              value={website}
              onChange={(e) => setWebsite(e.target.value)}
              placeholder="https://"
            />
          </div>
          <div className="input-group">
            <label htmlFor="plug-ig">Instagram</label>
            <input
              id="plug-ig"
              value={instagram}
              onChange={(e) => setInstagram(e.target.value)}
              placeholder="@handle"
            />
          </div>
          <div className="input-group">
            <label htmlFor="plug-niche">Niche</label>
            <input
              id="plug-niche"
              value={niche}
              onChange={(e) => setNiche(e.target.value)}
              placeholder="e.g. personal finance, cooking, fitness"
            />
          </div>
        </div>
        <div className="input-group">
          <label htmlFor="plug-niche-details">Details about niche</label>
          <textarea
            id="plug-niche-details"
            rows={5}
            value={nicheDetails}
            onChange={(e) => setNicheDetails(e.target.value)}
            placeholder="Who you talk to, what you stand for, what you never cover, the vibe of your content…"
          />
        </div>

        <h2 className="plug-section-title">Example topics</h2>
        <p className="text-muted plug-hint">
          Directions you already like. Search uses these as signals, not a copy list.
        </p>
        <div className="topic-chip-grid plug-chip-grid">
          {exampleTopics.map((topic, index) => (
            <span key={`${topic}-${index}`} className="topic-chip">
              <span className="topic-chip-text">{topic}</span>
              <button type="button" className="topic-remove" onClick={() => removeTopic(index)}>
                ×
              </button>
            </span>
          ))}
        </div>
        <div className="plug-inline-add">
          <input
            value={topicDraft}
            onChange={(e) => setTopicDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') addTopic(e)
            }}
            placeholder="Add an example topic"
          />
          <button type="button" className="btn btn-secondary" onClick={addTopic}>
            Add
          </button>
        </div>

        <h2 className="plug-section-title">Example scripts</h2>
        <p className="text-muted plug-hint">
          Optional. Paste scripts you like so new ones can follow the same voice. No format types.
        </p>
        {exampleScripts.map((script, index) => (
          <div key={index} className="input-group plug-script-sample">
            <label htmlFor={`plug-ex-script-${index}`}>Script {index + 1}</label>
            <textarea
              id={`plug-ex-script-${index}`}
              rows={6}
              value={script}
              onChange={(e) => {
                const next = [...exampleScripts]
                next[index] = e.target.value
                setExampleScripts(next)
              }}
              placeholder="Paste a spoken script you already like…"
            />
            {exampleScripts.length > 1 && (
              <button
                type="button"
                className="btn btn-sm btn-danger"
                onClick={() => setExampleScripts((prev) => prev.filter((_, i) => i !== index))}
              >
                Remove
              </button>
            )}
          </div>
        ))}
        <button
          type="button"
          className="btn btn-secondary"
          onClick={() => setExampleScripts((prev) => [...prev, ''])}
        >
          <i className="fa-solid fa-plus" /> Add example script
        </button>

        <h2 className="plug-section-title">Reference videos</h2>
        <p className="text-muted plug-hint">
          Links that capture the editing style you want. Paste a URL and add it.
        </p>
        <div className="topic-chip-grid plug-chip-grid">
          {referenceVideos.map((url, index) => (
            <span key={`${url}-${index}`} className="topic-chip plug-video-chip">
              <a href={url} target="_blank" rel="noreferrer" className="topic-chip-text" onClick={(e) => e.stopPropagation()}>
                {url}
              </a>
              <button
                type="button"
                className="topic-remove"
                onClick={() => setReferenceVideos((prev) => prev.filter((_, i) => i !== index))}
              >
                ×
              </button>
            </span>
          ))}
        </div>
        <div className="plug-inline-add">
          <input
            value={videoDraft}
            onChange={(e) => setVideoDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                const url = videoDraft.trim()
                if (!url) return
                if (referenceVideos.some((v) => v.toLowerCase() === url.toLowerCase())) {
                  setVideoDraft('')
                  return
                }
                setReferenceVideos((prev) => [...prev, url])
                setVideoDraft('')
              }
            }}
            placeholder="https://…"
          />
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => {
              const url = videoDraft.trim()
              if (!url) return
              if (referenceVideos.some((v) => v.toLowerCase() === url.toLowerCase())) {
                setVideoDraft('')
                return
              }
              setReferenceVideos((prev) => [...prev, url])
              setVideoDraft('')
            }}
          >
            Add
          </button>
        </div>

        <div className="plug-form-actions">
          <button type="submit" className="btn btn-primary" disabled={saving}>
            {saving ? 'Saving…' : 'Save profile'}
          </button>
        </div>
      </form>
    </div>
  )
}
